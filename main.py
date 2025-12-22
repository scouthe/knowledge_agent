import uvicorn
import asyncio
import uuid
import json
import xmltodict
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import PlainTextResponse
from wechatpy.crypto import WeChatCrypto
from wechatpy.replies import create_reply
from wechatpy.exceptions import InvalidSignatureException
from pydantic import BaseModel

from config import TOKEN, ENCODING_AES_KEY, CORP_ID
from core.wechat import SYSTEM_STATE, send_wecom_msg
from core.pipeline import process_content_to_obsidian
from utils.inbox import write_inbox_job, list_inbox_jobs, mark_inbox_done
from utils.logger import append_job_event, now_iso

app = FastAPI()
crypto = WeChatCrypto(TOKEN, ENCODING_AES_KEY, CORP_ID)

# === Inbox Worker ===
WORKER_LOCK = asyncio.Lock()
async def inbox_worker_loop():
    print("🧵 Inbox Worker 启动")
    while True:
        await asyncio.sleep(1.5)
        jobs = list_inbox_jobs()
        if not jobs: continue
        
        async with WORKER_LOCK:
            jobs = list_inbox_jobs()
            if not jobs: continue
            job_path = jobs[0]
            
            with open(job_path, "r", encoding="utf-8") as f:
                job = json.load(f)
            
            # 执行业务
            try:
                append_job_event(job["job_id"], "RUNNING", step="worker_pick")
                await process_content_to_obsidian(job["job_id"], job["content"], job["user_id"])
                mark_inbox_done(job_path)
            except Exception as e:
                print(f"Worker 异常: {e}")
                # 异常不移动文件，或移动到 error 文件夹

@app.on_event("startup")
async def startup():
    asyncio.create_task(inbox_worker_loop())

# === API Routes ===

class IngestPayload(BaseModel):
    user_id: str
    content: str

@app.post("/ingest")
async def ingest(payload: IngestPayload):
    """API 入口 (快捷指令)"""
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

@app.get("/healthz")
async def healthz():
    return PlainTextResponse("ok")

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
                reply = f"⚠️ IP 限制未解除，请修复: {SYSTEM_STATE['msg']}"
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

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8888, reload=True)