import os
import json
from config import INBOX_DIR, DATA_DIR

def write_inbox_job(job: dict) -> str:
    job_id = job["job_id"]
    path = os.path.join(INBOX_DIR, f"{job_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
    return path

def list_inbox_jobs() -> list[str]:
    files = []
    if not os.path.exists(INBOX_DIR): return []
    for fn in os.listdir(INBOX_DIR):
        if fn.endswith(".json"):
            files.append(os.path.join(INBOX_DIR, fn))
    files.sort(key=lambda p: os.path.getmtime(p))
    return files

def mark_inbox_done(job_path: str):
    done_dir = os.path.join(DATA_DIR, "done")
    os.makedirs(done_dir, exist_ok=True)
    base = os.path.basename(job_path)
    os.rename(job_path, os.path.join(done_dir, base))