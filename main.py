import uvicorn
import asyncio
import uuid
import json
import os
import xmltodict
import chromadb # 👈 新增：引入向量数据库库
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
    CHROMA_DB_PATH,    # 👈 确保 config.py 里有这个变量 (例如: "./chroma_db")
    OBSIDIAN_ROOT   # 👈 确保 config.py 里有这个变量
)

from core.wechat import SYSTEM_STATE, send_wecom_msg
from core.pipeline import process_content_to_obsidian
from utils.inbox import write_inbox_job, list_inbox_jobs, mark_inbox_done
from utils.logger import append_job_event, now_iso

app = FastAPI()

# === 1. 初始化服务 ===
# 微信加密套件
crypto = WeChatCrypto(TOKEN, ENCODING_AES_KEY, CORP_ID)

# 向量数据库客户端 (用于清理逻辑)
print(f"🔌 连接向量数据库: {CHROMA_DB_PATH}")
chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
collection = chroma_client.get_or_create_collection(name="knowledge_base")

# === 2. 核心功能函数 ===

def sync_prune_vectors():
    """
    核心逻辑：同步向量库与文件系统
    检查向量库里的 metadata 对应的文件是否还在硬盘上，不在则删除索引。
    """
    print("🧹 开始执行向量库清理...")
    
    # 获取库里所有数据 (只取 id 和 metadata)
    try:
        all_data = collection.get(include=['metadatas'])
    except Exception as e:
        return {"status": "error", "message": f"读取向量库失败: {e}"}
    
    ids_to_delete = []
    active_paths = set()
    deleted_count = 0
    
    total_docs = len(all_data['ids']) if all_data['ids'] else 0
    print(f"📊 当前库内共有 {total_docs} 个切片，正在核对...")

    for i, doc_id in enumerate(all_data['ids']):
        meta = all_data['metadatas'][i]
        
        # 获取文件路径
        # 兼容逻辑：优先取 metadata 里的 full_path，没有则尝试用 rel_path 拼
        file_path = meta.get('path') or meta.get('source')
        
        # 如果是相对路径，尝试拼接 OBSIDIAN_ROOT
        if file_path and not os.path.isabs(file_path):
             # 简单的防错：如果 file_path 已经是绝对路径就不会拼
             potential_path = os.path.join(OBSIDIAN_ROOT, file_path)
             if os.path.exists(potential_path):
                 file_path = potential_path

        if file_path:
            if not os.path.exists(file_path):
                # ❌ 文件不在硬盘上了 -> 标记删除
                ids_to_delete.append(doc_id)
                # print(f"  [过期] {file_path}")
            else:
                active_paths.add(file_path)
        else:
            # ⚠️ 没有路径信息的脏数据，可选择删除或保留，这里暂时保留
            pass

    # 执行批量删除
    if ids_to_delete:
        collection.delete(ids=ids_to_delete)
        deleted_count = len(ids_to_delete)
        print(f"🗑️ 已清理 {deleted_count} 个无效切片")
    else:
        print("✅ 向量库与文件系统完全一致。")
        
    return {
        "status": "success", 
        "total_checked": total_docs,
        "deleted_chunks": deleted_count,
        "active_files_count": len(active_paths)
    }

# === 3. 数据模型定义 ===

class SharePayload(BaseModel):
    url: str
    note: str = ""

class IngestPayload(BaseModel):
    user_id: str
    content: str

# === 4. API 路由 ===

@app.post("/api/share")
async def share_content(
    payload: SharePayload, 
    x_api_key: str = Header(None)
):
    """接收安卓手机 HTTP Shortcuts 分享"""
    # 简单的安全校验
    if x_api_key != API_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")

    print(f"📱 收到手机分享: {payload.url}")

    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "user_id": "mobile_user",
        "content": payload.url + ("\n" + payload.note if payload.note else ""),
        "received_at": now_iso(),
        "source": "android_share"
    }
    write_inbox_job(job)
    return {"status": "success", "job_id": job_id}

@app.post("/ingest")
async def ingest(payload: IngestPayload):
    """通用入库接口 (供 WebUI 速记等使用)"""
    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "user_id": payload.user_id,
        "content": payload.content,
        "received_at": now_iso(),
        "source": "api"
    }
    write_inbox_job(job)
    return {"status": "accepted", "job_id": job_id}

@app.post("/prune")
async def api_prune_db():
    """清理无效向量索引接口"""
    try:
        result = sync_prune_vectors()
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/healthz")
async def healthz():
    return PlainTextResponse("ok")

# === 5. 微信相关路由 ===

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
                    "source": "wechat"
                })
                reply = f"✅ 已入队\nJob: {job_id[:8]}"
        else:
            reply = "暂不支持非文本"

        ret = create_reply(reply, message=msg).render()
        return PlainTextResponse(crypto.encrypt_message(ret, nonce, timestamp))
    except InvalidSignatureException:
        return "fail"

# === 6. 后台 Worker 逻辑 ===

WORKER_LOCK = asyncio.Lock()
async def inbox_worker_loop():
    print("🧵 Inbox Worker 启动")
    while True:
        await asyncio.sleep(1.5)
        # 简单检查是否有文件，减少 I/O
        if not list_inbox_jobs(): 
            continue
        
        async with WORKER_LOCK:
            jobs = list_inbox_jobs()
            if not jobs: continue
            job_path = jobs[0]
            
            try:
                with open(job_path, "r", encoding="utf-8") as f:
                    job = json.load(f)
            
                # 执行业务
                append_job_event(job["job_id"], "RUNNING", step="worker_pick")
                await process_content_to_obsidian(job["job_id"], job["content"], job["user_id"])
                mark_inbox_done(job_path)
            except Exception as e:
                print(f"❌ Worker 异常: {e}")
                # 遇到错误可以移动到 error 目录，防止死循环 (Day 4 优化点)
                # 目前简单重命名跳过
                error_path = job_path + ".err"
                if os.path.exists(job_path):
                    os.rename(job_path, error_path)

@app.on_event("startup")
async def startup():
    asyncio.create_task(inbox_worker_loop())

if __name__ == "__main__":
    # reload=True 在生产环境(systemctl)建议关闭，但在开发调试很有用
    # 如果用 systemd 启动，它会直接运行，不会看 reload 参数
    uvicorn.run("main:app", host="0.0.0.0", port=8888, reload=True,
                reload_excludes=[".git", ".venv", "__pycache__", "*.md", "./chroma_db/*"])