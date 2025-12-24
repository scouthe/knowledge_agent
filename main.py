import uvicorn
import asyncio
import uuid
import json
import os
import re
import time
import xmltodict
import chromadb
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, Header, UploadFile, File, Form
from fastapi.responses import PlainTextResponse
from wechatpy.crypto import WeChatCrypto
from wechatpy.replies import create_reply
from wechatpy.exceptions import InvalidSignatureException
from pydantic import BaseModel

# 引入配置
from config import (
    TOKEN, 
    ENCODING_AES_KEY, 
    CORP_ID, 
    API_SECRET_KEY, 
    CHROMA_DB_PATH,    # ⚠️ 请确认 config.py 里是 CHROMA_PATH 还是 CHROMA_DB_PATH，这里要一致
    OBSIDIAN_ROOT,
    SPECIAL_USER
)

from core.wechat import SYSTEM_STATE, send_wecom_msg
from core.pipeline import process_content_to_obsidian
from utils.inbox import write_inbox_job, list_inbox_jobs, mark_inbox_done
from utils.logger import append_job_event, now_iso, get_job_latest_status # 👈 引入新函数
from utils.auth import (
    init_auth_db,
    create_user,
    verify_user,
    issue_token,
    verify_token,
    reset_password,
    list_users,
    admin_set_password,
    delete_user,
)
from utils.rebuild import rebuild_user_vectors
from utils.daily_summary import generate_daily_summary, build_daily_list
from utils.voice import transcribe_audio
from core.retriever import hybrid_search
from core.llm import call_llm_analysis
from core.llm import chat as llm_chat
from core.storage import resolve_user_root

app = FastAPI()

# === 1. 初始化服务 ===
crypto = WeChatCrypto(TOKEN, ENCODING_AES_KEY, CORP_ID)

print(f"🔌 连接向量数据库: {CHROMA_DB_PATH}")
chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
collection = chroma_client.get_or_create_collection(name="knowledge_base")

# === 2. 核心功能函数 ===

def sync_prune_vectors(user_root: str):
    """清理无效索引 (安全版)"""
    print("🧹 开始执行向量库清理 (安全模式)...")
    try:
        all_data = collection.get(include=['metadatas'])
    except Exception as e:
        return {"status": "error", "message": f"读取向量库失败: {e}"}
    
    ids_to_delete = []
    active_paths = set()
    missing_path_count = 0
    ambiguous_hash_count = 0
    
    print("📂 正在扫描本地文件系统...")
    hash6_map = {}
    for root, dirs, files in os.walk(user_root):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for file in files:
            if not file.endswith('.md'):
                continue
            match = re.search(r'__([0-9a-fA-F]{6})\.md$', file)
            if not match:
                continue
            hash6 = match.group(1).lower()
            hash6_map.setdefault(hash6, []).append(os.path.join(root, file))
    
    print(f"✅ 本地共扫描到 {sum(len(v) for v in hash6_map.values())} 个 Markdown 文件(可解析hash)")
    
    total_docs = len(all_data['ids']) if all_data['ids'] else 0

    for i, doc_id in enumerate(all_data['ids']):
        meta = all_data['metadatas'][i]
        # 兼容不同版本的字段名
        stored_path = meta.get('file_path') or None
        
        if not stored_path:
            parent_id = meta.get("parent_id") or doc_id.split("_")[0]
            hash6 = parent_id[:6].lower() if parent_id else ""
            candidates = hash6_map.get(hash6, [])
            if len(candidates) == 1:
                stored_path = candidates[0]
            elif len(candidates) > 1:
                ambiguous_hash_count += 1
                continue
            else:
                missing_path_count += 1
                continue

        if not os.path.isabs(stored_path):
            stored_path = os.path.join(user_root, stored_path)

        if not stored_path.startswith(user_root):
            continue
        if os.path.exists(stored_path):
            active_paths.add(stored_path)
        else:
            print(f"🗑️ 发现失效索引: {stored_path}")
            ids_to_delete.append(doc_id)

    deleted_count = 0
    if ids_to_delete:
        collection.delete(ids=ids_to_delete)
        deleted_count = len(ids_to_delete)
        print(f"🧹 清理完成: 删除了 {deleted_count} 个失效切片")
    else:
        print("✅ 校验通过: 没有发现失效索引")
        
    return {
        "status": "success", 
        "total_checked": total_docs,
        "deleted_chunks": deleted_count,
        "active_files_count": len(active_paths),
        "missing_path_count": missing_path_count,
        "ambiguous_hash_count": ambiguous_hash_count
    }

# === 3. 数据模型 ===
class SharePayload(BaseModel):
    url: str
    note: str = ""

class RegisterPayload(BaseModel):
    username: str
    password: str

class LoginPayload(BaseModel):
    username: str
    password: str

class ResetPayload(BaseModel):
    username: str
    old_password: str
    new_password: str

class AdminPasswordPayload(BaseModel):
    username: str
    new_password: str

class AdminUserPayload(BaseModel):
    username: str
    password: str

class CategoryPayload(BaseModel):
    name: str

class IngestPayload(BaseModel):
    content: str
    mode: str = "auto"
    folder: str | None = None

def require_user(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ", 1)[1].strip()
    username = verify_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")
    return username

def require_admin(authorization: str | None) -> str:
    username = require_user(authorization)
    if username != SPECIAL_USER:
        raise HTTPException(status_code=403, detail="Admin only")
    return username

# === 4. API 路由 ===

@app.post("/api/share")
async def share_content(payload: SharePayload, x_api_key: str = Header(None)):
    if x_api_key != API_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")

    print(f"📱 收到手机分享: {payload.url}")
    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "user_id": "mobile_user",
        "content": payload.url + ("\n" + payload.note if payload.note else ""),
        "received_at": now_iso(),
        "source": "android_share",
        "process_mode": "crawl" # 手机分享通常是链接
    }
    write_inbox_job(job)
    return {"status": "success", "job_id": job_id}

@app.post("/auth/register")
async def register(payload: RegisterPayload):
    ok, msg = create_user(payload.username, payload.password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success"}

@app.post("/auth/login")
async def login(payload: LoginPayload):
    if not verify_user(payload.username, payload.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = issue_token(payload.username)
    return {"token": token, "username": payload.username}

@app.post("/auth/reset")
async def reset(payload: ResetPayload):
    ok, msg = reset_password(payload.username, payload.old_password, payload.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success"}

@app.get("/admin/users")
async def admin_users(authorization: str = Header(None)):
    require_admin(authorization)
    return {"users": list_users()}

@app.post("/admin/users")
async def admin_create_user(payload: AdminUserPayload, authorization: str = Header(None)):
    require_admin(authorization)
    ok, msg = create_user(payload.username, payload.password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success"}

@app.post("/admin/users/reset")
async def admin_reset_user(payload: AdminPasswordPayload, authorization: str = Header(None)):
    require_admin(authorization)
    ok, msg = admin_set_password(payload.username, payload.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success"}

@app.delete("/admin/users/{username}")
async def admin_delete_user(username: str, authorization: str = Header(None)):
    require_admin(authorization)
    ok, msg = delete_user(username)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success"}

@app.post("/ingest")
async def ingest(payload: IngestPayload, authorization: str = Header(None)):
    username = require_user(authorization)
    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "user_id": username,
        "content": payload.content,
        "received_at": now_iso(),
        "source": "api",
        "process_mode": payload.mode,
        "folder": payload.folder
    }
    write_inbox_job(job)
    return {"status": "accepted", "job_id": job_id}

@app.post("/api/category")
async def create_category(payload: CategoryPayload, authorization: str = Header(None)):
    username = require_user(authorization)
    safe_name = payload.name.strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="Empty category")
    root = resolve_user_root(username)
    path = os.path.join(root, safe_name)
    os.makedirs(os.path.join(path, "Notes"), exist_ok=True)
    os.makedirs(os.path.join(path, "Articles"), exist_ok=True)
    return {"status": "success", "path": path}

@app.get("/api/categories")
async def list_categories(authorization: str = Header(None)):
    username = require_user(authorization)
    root = resolve_user_root(username)
    categories = []
    defaults = {"Notes", "Articles", "Inbox", ".obsidian"}
    try:
        for name in os.listdir(root):
            path = os.path.join(root, name)
            if os.path.isdir(path) and name not in defaults and not name.startswith("."):
                categories.append(name)
    except Exception:
        pass
    categories.sort()
    return {"categories": categories}

@app.post("/api/upload")
async def upload_file(
    authorization: str = Header(None),
    file: UploadFile = File(...),
    folder: str | None = Form(None),
):
    username = require_user(authorization)
    user_root = resolve_user_root(username)
    try:
        from markitdown import MarkItDown
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"MarkItDown 不可用: {e}")

    suffix = os.path.splitext(file.filename or "")[1]
    if not suffix:
        suffix = ".bin"
    tmp_path = os.path.join("/tmp", f"upload_{uuid.uuid4().hex}{suffix}")
    with open(tmp_path, "wb") as f:
        f.write(await file.read())

    try:
        md = MarkItDown().convert(tmp_path).text_content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析失败: {e}")
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    clean_name = os.path.splitext(file.filename or "upload")[0]
    save_name = f"{time.strftime('%Y%m%d_%H%M%S')}_{clean_name}.md"
    target_folder = folder.strip() if folder else "Inbox"
    dir_path = os.path.join(user_root, target_folder)
    os.makedirs(dir_path, exist_ok=True)
    full_path = os.path.join(dir_path, save_name)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(f"---\ntitle: {clean_name}\ntype: upload\n---\n\n{md}")

    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "user_id": username,
        "content": f"上传文件: {clean_name}\n{md[:500]}...",
        "received_at": now_iso(),
        "source": "upload",
        "process_mode": "note",
        "folder": folder,
    }
    write_inbox_job(job)
    return {"status": "accepted", "job_id": job_id, "path": full_path}

@app.post("/api/ingest_voice")
async def ingest_voice(
    authorization: str = Header(None),
    file: UploadFile = File(...),
    folder: str | None = Form(None),
):
    username = require_user(authorization)
    suffix = os.path.splitext(file.filename or "")[1]
    if not suffix:
        suffix = ".wav"
    tmp_path = os.path.join("/tmp", f"voice_{uuid.uuid4().hex}{suffix}")
    with open(tmp_path, "wb") as f:
        f.write(await file.read())

    try:
        text = transcribe_audio(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"语音转文字失败: {e}")
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    if not text.strip():
        raise HTTPException(status_code=400, detail="语音内容为空")

    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "user_id": username,
        "content": text,
        "received_at": now_iso(),
        "source": "voice",
        "process_mode": "note",
        "folder": folder,
    }
    write_inbox_job(job)
    return {"status": "accepted", "job_id": job_id, "text": text[:200]}

@app.post("/api/rebuild_vectors")
async def api_rebuild_vectors(authorization: str = Header(None)):
    username = require_user(authorization)
    user_root = resolve_user_root(username)
    count = rebuild_user_vectors(user_root, username)
    return {"status": "success", "chunks": count}

@app.post("/api/daily_summary")
async def api_daily_summary(authorization: str = Header(None)):
    username = require_user(authorization)
    user_root = resolve_user_root(username)
    path, msg = generate_daily_summary(user_root, username)
    if not path:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "path": path, "mode": msg}

@app.get("/api/daily_list")
async def api_daily_list(offset: int = 0, authorization: str = Header(None)):
    username = require_user(authorization)
    user_root = resolve_user_root(username)
    content = build_daily_list(user_root, username, offset)
    return {"content": content}

@app.post("/api/chat")
async def api_chat(payload: dict, authorization: str = Header(None)):
    username = require_user(authorization)
    query = (payload.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Empty query")

    hits = hybrid_search(query, top_k=8, user_id=username)
    docs = [h.get("content", "") for h in hits if h.get("content")]
    context_str = "\n\n".join([f"【来源{i+1}】: {d}" for i, d in enumerate(docs[:6])])

    if not context_str:
        # 无命中则走通用对话
        answer = llm_chat(query)
        return {"answer": answer}

    # 纠偏式回答
    draft = llm_chat(query)
    correction_prompt = (
        "你是一个审校助手。请依据【知识库片段】对【初稿回答】进行纠偏：\n"
        "1) 如果初稿与知识库冲突，必须修正。\n"
        "2) 如果初稿有缺失且知识库有信息，请补充。\n"
        "3) 不要添加知识库之外的新事实。\n"
        "4) 输出最终答案，保持回答详细。\n"
        f"\n【初稿回答】:\n{draft}\n"
        f"\n【知识库片段】:\n{context_str}\n"
    )
    answer = llm_chat(query, system_prompt=correction_prompt)
    return {"answer": answer}



# ✨ 新增：状态查询接口
@app.get("/api/status/{job_id}")
async def check_job_status(job_id: str):
    return get_job_latest_status(job_id)

@app.post("/prune")
async def api_prune_db(authorization: str = Header(None)):
    try:
        username = require_user(authorization)
        user_root = resolve_user_root(username)
        return sync_prune_vectors(user_root)
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/healthz")
async def healthz():
    return PlainTextResponse("ok")

# === 5. 微信路由 (略，保持原样) ===
@app.get("/wechat")
async def verify_url(msg_signature: str, timestamp: str, nonce: str, echostr: str):
    try:
        xml = f"<xml><Encrypt><![CDATA[{echostr}]]></Encrypt><ToUserName><![CDATA[{CORP_ID}]]></ToUserName></xml>"
        return PlainTextResponse(crypto.decrypt_message(xml, msg_signature, timestamp, nonce))
    except Exception:
        raise HTTPException(500)

@app.post("/wechat")
async def receive_msg(request: Request, msg_signature: str, timestamp: str, nonce: str):
    body = await request.body()
    try:
        xml = crypto.decrypt_message(body.decode("utf-8"), msg_signature, timestamp, nonce)
        msg = xmltodict.parse(xml)['xml']
        
        if msg.get('MsgType') == 'text':
            if SYSTEM_STATE["error"]:
                reply = f"⚠️ IP 限制未解除: {SYSTEM_STATE['msg']}"
            else:
                job_id = str(uuid.uuid4())
                write_inbox_job({
                    "job_id": job_id,
                    "user_id": msg.get('FromUserName'),
                    "content": msg.get('Content', ''),
                    "received_at": now_iso(),
                    "source": "wechat",
                    "process_mode": "auto"
                })
                reply = f"✅ 已入队\nJob: {job_id[:8]}"
        else:
            reply = "暂不支持非文本"

        ret = create_reply(reply, message=msg).render()
        return PlainTextResponse(crypto.encrypt_message(ret, nonce, timestamp))
    except InvalidSignatureException:
        return "fail"

# === 6. Worker 逻辑 (已修复变量作用域错误) ===
WORKER_LOCK = asyncio.Lock()
async def inbox_worker_loop():
    print("🧵 Inbox Worker 启动")
    while True:
        await asyncio.sleep(1.5)
        if not list_inbox_jobs(): 
            continue
        
        async with WORKER_LOCK:
            jobs = list_inbox_jobs()
            if not jobs: continue
            job_path = jobs[0]
            
            try:
                # 1. 先读取文件
                with open(job_path, "r", encoding="utf-8") as f:
                    job = json.load(f)
                
                # 2. ✅ 现在可以安全获取 mode 了
                mode = job.get("process_mode", "auto")
                folder = job.get("folder")

                # 3. 执行业务
                append_job_event(job["job_id"], "RUNNING", step="worker_pick")
                
                await process_content_to_obsidian(
                    job["job_id"], 
                    job["content"], 
                    job["user_id"],
                    mode=mode,
                    folder=folder
                )
                
                mark_inbox_done(job_path)
            except Exception as e:
                print(f"❌ Worker 异常: {e}")
                error_path = job_path + ".err"
                if os.path.exists(job_path):
                    os.rename(job_path, error_path)

@app.on_event("startup")
async def startup():
    init_auth_db()
    asyncio.create_task(inbox_worker_loop())

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8888, reload=True,
                reload_excludes=[".git", ".venv", "__pycache__", "*.md", "./chroma_db/*"])
