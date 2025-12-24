import os
import datetime
from pathlib import Path

import httpx

from config import LLM_API_URL, LLM_MODEL
from core.storage import collection as chroma_collection


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].lstrip()
    return text


def _extract_title(md_text: str, fallback: str) -> str:
    for line in md_text.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or fallback
    return fallback


def _extract_excerpt(md_text: str, max_chars: int = 1200) -> str:
    body = _strip_frontmatter(md_text)
    body = body.replace("\r", "")
    return body[:max_chars].strip()


def _collect_daily_docs(user_id: str, date_str: str, batch_size: int = 200):
    items = {}
    offset = 0
    while True:
        res = chroma_collection.get(include=["metadatas"], limit=batch_size, offset=offset)
        metadatas = res.get("metadatas") or []
        if not metadatas:
            break
        for meta in metadatas:
            if meta.get("user_id") != user_id:
                continue
            created_at = meta.get("created_at", "")
            if date_str not in created_at:
                continue
            doc_id = meta.get("parent_id") or meta.get("doc_id")
            if not doc_id:
                continue
            items[doc_id] = meta
        if len(metadatas) < batch_size:
            break
        offset += batch_size
    return list(items.values())


def _group_item(meta: dict) -> str:
    category = meta.get("category", "")
    if category == "个人笔记":
        return "notes"
    return "articles"


def _parse_created_at(created_at: str) -> datetime.datetime | None:
    if not created_at:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.datetime.strptime(created_at, fmt)
        except Exception:
            continue
    try:
        return datetime.datetime.fromisoformat(created_at)
    except Exception:
        return None


def _latest_doc_time(metas: list[dict]) -> datetime.datetime | None:
    latest = None
    for meta in metas:
        dt = _parse_created_at(meta.get("created_at", ""))
        if not dt:
            continue
        if not latest or dt > latest:
            latest = dt
    return latest


def generate_daily_summary(user_root: str, user_id: str, date_str: str | None = None):
    if not date_str:
        date_str = datetime.date.today().strftime("%Y-%m-%d")

    metas = _collect_daily_docs(user_id, date_str)
    if not metas:
        return None, f"{date_str} 没有可用内容"

    year_month = date_str[:7]
    out_dir = os.path.join(user_root, "Daily_Log", year_month)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{date_str}_今日总结.md")
    if os.path.exists(out_path):
        latest_dt = _latest_doc_time(metas)
        summary_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(out_path))
        if latest_dt and latest_dt <= summary_mtime:
            return out_path, "cached"

    notes = []
    articles = []
    content_blocks = []

    for meta in metas:
        file_path = meta.get("file_path", "")
        if not file_path or not os.path.exists(file_path):
            continue
        md_text = Path(file_path).read_text(encoding="utf-8", errors="ignore")
        title = _extract_title(md_text, Path(file_path).stem)
        link = f"[[{Path(file_path).stem}]]"
        excerpt = _extract_excerpt(md_text)
        block = f"### {link}\n{excerpt}"
        content_blocks.append(block)
        if _group_item(meta) == "notes":
            notes.append(f"- {link}")
        else:
            articles.append(f"- {link}")

    if not content_blocks:
        return None, f"{date_str} 没有可用内容"

    content_text = "\n\n".join(content_blocks)
    if len(content_text) > 60000:
        content_text = content_text[:60000]

    system_prompt = (
        "你是一个专业的个人知识库助手。请基于用户今天的全部记录生成今日总结。\n"
        "要求：\n"
        "1) 必须使用 Obsidian 的 [[文件名]] 作为引用链接。\n"
        "2) 语气客观、鼓励性，区分工作与生活。\n"
        "3) 不要编造未出现的事实。\n"
        "输出格式：\n"
        f"# 📅 {date_str} 今日总结\n\n"
        "## 📝 核心摘要\n"
        "（3-5句概括）\n\n"
        "## 💼 工作与项目\n"
        "- **进展**：...\n"
        "- **决策**：...\n"
        "- **阻塞**：...\n\n"
        "## 🌈 生活与记录\n"
        "- **记录**：...\n"
        "- **状态**：...\n\n"
        "## 📚 信息摄入 (Input)\n"
        "- ...\n\n"
        "## 💡 灵感与收获\n"
        "- ...\n\n"
        "## ✅ 明日建议\n"
        "- ...\n\n"
        "## 🤖 AI 洞察\n"
        "- ...\n"
    )

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content_text},
        ],
        "temperature": 0.5,
    }

    try:
        resp = httpx.post(LLM_API_URL, json=payload, timeout=120)
        data = resp.json()
        summary = data["choices"][0]["message"]["content"]
    except Exception as e:
        return None, f"LLM 生成失败: {e}"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(summary)

    return out_path, "updated"


def build_daily_list(user_root: str, user_id: str, offset_days: int) -> str:
    date_str = (datetime.date.today() - datetime.timedelta(days=offset_days)).strftime("%Y-%m-%d")
    metas = _collect_daily_docs(user_id, date_str)
    if not metas:
        return f"📭 {date_str} 暂无内容。"

    grouped = {}
    for meta in metas:
        path = meta.get("file_path", "")
        if not path or not os.path.exists(path):
            continue
        rel = os.path.relpath(path, user_root)
        folder = rel.split(os.sep)[0] if rel else "默认"
        category = folder if folder not in ("Notes", "Articles", "Inbox") else "默认"
        item_type = "笔记" if meta.get("category") == "个人笔记" else "网页"
        title = meta.get("title", "无标题")
        grouped.setdefault(category, {}).setdefault(item_type, set()).add(title)

    lines = [f"📅 {date_str}"]
    for category in sorted(grouped.keys()):
        lines.append("")
        lines.append(f"分类：{category}")
        for item_type in ("笔记", "网页"):
            titles = sorted(grouped[category].get(item_type, []))
            if not titles:
                continue
            lines.append(f"\n{item_type}（{len(titles)}）")
            for title in titles:
                lines.append(f"《{title}》")
    return "\n".join(lines)
