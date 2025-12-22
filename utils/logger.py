import os
import json
import time
from config import JOBS_LOG_PATH

def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())

def append_job_event(job_id: str, status: str, *, step: str = "", url: str = "", user_id: str = "",
                     message: str = "", error: str | None = None, extra: dict | None = None):
    rec = {
        "ts": now_iso(),
        "job_id": job_id,
        "status": status,
        "step": step,
        "url": url,
        "user_id": user_id,
        "message": message,
        "error": error,
    }
    if extra:
        rec["extra"] = extra
    
    try:
        with open(JOBS_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"❌ 日志写入失败: {e}")