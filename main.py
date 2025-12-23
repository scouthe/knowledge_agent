import uvicorn
import asyncio
import uuid
import json
import os
import re
import xmltodict
import chromadb
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, Header
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
    OBSIDIAN_ROOT
)

from core.wechat import SYSTEM_STATE, send_wecom_msg
from core.pipeline import process_content_to_obsidian
from utils.inbox import write_inbox_job, list_inbox_jobs, mark_inbox_done
from utils.logger import append_job_event, now_iso, get_job_latest_status # 👈 引入新函数

app = FastAPI()

# === 1. 初始化服务 ===
crypto = WeChatCrypto(TOKEN, ENCODING_AES_KEY, CORP_ID)

print(f"🔌 连接向量数据库: {CHROMA_DB_PATH}")
chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
collection = chroma_client.get_or_create_collection(name="knowledge_base")

# === 2. 核心功能函数 ===

def sync_prune_vectors():
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
    for root, dirs, files in os.walk(OBSIDIAN_ROOT):
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
            stored_path = os.path.join(OBSIDIAN_ROOT, stored_path)

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

class IngestPayload(BaseModel):
    user_id: str
    content: str
    mode: str = "auto"

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

@app.post("/ingest")
async def ingest(payload: IngestPayload):
    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "user_id": payload.user_id,
        "content": payload.content,
        "received_at": now_iso(),
        "source": "api",
        "process_mode": payload.mode
    }
    write_inbox_job(job)
    return {"status": "accepted", "job_id": job_id}

# ✨ 新增：状态查询接口
@app.get("/api/status/{job_id}")
async def check_job_status(job_id: str):
    return get_job_latest_status(job_id)

@app.post("/prune")
async def api_prune_db():
    try:
        return sync_prune_vectors()
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

                # 3. 执行业务
                append_job_event(job["job_id"], "RUNNING", step="worker_pick")
                
                await process_content_to_obsidian(
                    job["job_id"], 
                    job["content"], 
                    job["user_id"],
                    mode=mode
                )
                
                mark_inbox_done(job_path)
            except Exception as e:
                print(f"❌ Worker 异常: {e}")
                error_path = job_path + ".err"
                if os.path.exists(job_path):
                    os.rename(job_path, error_path)

@app.on_event("startup")
async def startup():
    asyncio.create_task(inbox_worker_loop())

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8888, reload=True,
                reload_excludes=[".git", ".venv", "__pycache__", "*.md", "./chroma_db/*"])
