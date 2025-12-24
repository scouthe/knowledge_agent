import os
import re
import hashlib
from pathlib import Path

from core.storage import save_to_vector_db
from utils.helpers import url_hash


def parse_frontmatter(md_text: str) -> dict:
    if not md_text.startswith("---"):
        return {}
    parts = md_text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm = {}
    for line in parts[1].splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        fm[key.strip()] = val.strip().strip('"')
    return fm


def extract_ai_analysis(md_text: str) -> str:
    lines = md_text.splitlines()
    in_block = False
    collected = []
    for line in lines:
        if line.startswith("> [!ABSTRACT]"):
            in_block = True
            continue
        if in_block:
            if line.strip().startswith("---"):
                break
            if line.strip().startswith(">"):
                collected.append(line.lstrip(">").strip())
            elif line.strip() == "":
                collected.append("")
            else:
                break
    return "\n".join(collected).strip()


def load_markdown(path: Path, user_id: str) -> tuple[dict, dict]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fm = parse_frontmatter(text)
    title_match = re.search(r"^#\s+(.+)$", text, flags=re.M)
    title = title_match.group(1).strip() if title_match else fm.get("kb_title", path.stem)
    content = text.split("\n\n## 原文内容\n\n", 1)[-1] if "## 原文内容" in text else text
    source = fm.get("source", "")
    doc_id = fm.get("doc_id", "")
    if not doc_id:
        if source:
            doc_id = url_hash(source)
        else:
            doc_id = hashlib.md5(content.encode("utf-8")).hexdigest()
    raw_data = {
        "content": content,
        "category": fm.get("category", "文章阅读"),
        "url": source,
        "doc_id": doc_id,
        "created_at": fm.get("created", ""),
        "user_id": fm.get("user_id", "") or user_id,
        "folder": fm.get("folder", ""),
    }
    ai_analysis = extract_ai_analysis(text)
    ai_data = {
        "kb_title": title,
        "summary": fm.get("summary", ""),
        "analysis": ai_analysis,
        "tags": [],
    }
    return raw_data, ai_data


def rebuild_user_vectors(user_root: str, user_id: str) -> int:
    total = 0
    if not os.path.exists(user_root):
        return 0
    for md in Path(user_root).rglob("*.md"):
        raw_data, ai_data = load_markdown(md, user_id)
        if not raw_data.get("doc_id"):
            continue
        try:
            count = save_to_vector_db(raw_data, ai_data, str(md), raw_data["doc_id"])
            total += count
        except Exception:
            continue
    return total
