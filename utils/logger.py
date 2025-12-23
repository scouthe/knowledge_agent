import os
import json
import time
from config import JOBS_LOG_PATH

def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())

import os # 确保引入 os

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
        log_dir = os.path.dirname(JOBS_LOG_PATH)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)

        with open(JOBS_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            # ✨ 新增：强制刷盘，防止延迟
            f.flush()
            os.fsync(f.fileno()) 
    except Exception as e:
        print(f"❌ 日志写入失败: {e}")

# ✨ 新增：用于前端查询任务状态
def get_job_latest_status(job_id: str):
    """
    倒序读取日志文件，查找指定 Job ID 的最新状态
    """
    if not os.path.exists(JOBS_LOG_PATH):
        return {"status": "PENDING", "step": "queue", "message": "日志文件未生成"}

    found_entry = None
    try:
        with open(JOBS_LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
            # 倒序查找，效率最高
            for line in reversed(lines):
                try:
                    entry = json.loads(line)
                    if entry.get("job_id") == job_id:
                        found_entry = entry
                        break 
                except:
                    continue
    except Exception:
        pass

    if found_entry:
        return {
            "status": found_entry.get("status", "UNKNOWN"),
            "step": found_entry.get("step", ""),
            "message": found_entry.get("message", ""),
            "error": found_entry.get("error", "")
        }
    
    return {"status": "PENDING", "step": "queue", "message": "排队中..."}