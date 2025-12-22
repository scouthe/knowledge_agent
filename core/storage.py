import os
import json
import time
import hashlib
import chromadb
from chromadb.utils import embedding_functions
from config import (
    OBSIDIAN_ROOT, CHROMA_DB_PATH, EMBEDDING_API_URL, EMBEDDING_MODEL_NAME,
    CHROMA_COLLECTION_NAME, MIN_CONTENT_LENGTH, CHUNK_SIZE, CHUNK_OVERLAP
)
from utils.helpers import sanitize_filename, url_hash

# === 1. 初始化向量数据库 ===
print("🧠 正在初始化 ChromaDB...")
chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)

# 自定义 OpenAI 兼容的 Embedding 函数
emb_fn = embedding_functions.OpenAIEmbeddingFunction(
    api_key="lm-studio",
    api_base=EMBEDDING_API_URL,
    model_name=EMBEDDING_MODEL_NAME
)

collection = chroma_client.get_or_create_collection(
    name=CHROMA_COLLECTION_NAME,
    embedding_function=emb_fn
)
print(f"✅ ChromaDB 就绪: {CHROMA_COLLECTION_NAME}")


# === 2. 工具函数：文本分块 (Simple Chunking) ===
def split_text_into_chunks(text: str, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """
    简单的文本分块策略：
    1. 先按双换行符 \n\n 切分 (段落)
    2. 如果段落太长，再强行截断
    """
    if not text: return []
    
    chunks = []
    # 按段落粗分
    paragraphs = text.split('\n\n')
    
    current_chunk = ""
    
    for para in paragraphs:
        para = para.strip()
        if not para: continue
        
        # 如果当前块 + 新段落 没超限，就拼起来
        if len(current_chunk) + len(para) < chunk_size:
            current_chunk += "\n\n" + para
        else:
            # 如果超限了，先把旧的存了
            if current_chunk:
                chunks.append(current_chunk.strip())
            
            # 如果这一段本身就巨长 (超过 chunk_size)，只能强行切分
            if len(para) > chunk_size:
                for i in range(0, len(para), chunk_size - overlap):
                    chunks.append(para[i:i + chunk_size])
                current_chunk = "" # 切完清空
            else:
                # 这一段作为新块的开始
                current_chunk = para
                
    # 最后一个没存的存进去
    if current_chunk:
        chunks.append(current_chunk.strip())
        
    return chunks


# === 3. 核心：保存到 Markdown (Truth) ===
# (这部分和你昨天的代码基本一致，保留即可)
def format_analysis_to_markdown(analysis_data):
    if not analysis_data: return "> 暂无分析"
    lines = []
    if isinstance(analysis_data, dict):
        for k, v in analysis_data.items(): lines.append(f"* 📌 **{k}**: {v}")
    elif isinstance(analysis_data, str):
        lines = analysis_data.split('\n')
    else:
        lines = [str(analysis_data)]
    return "\n".join([f"> {line}" for line in lines if line.strip()])

def save_to_obsidian(raw_data: dict, ai_data: dict):
    # ... (此处保留昨天 save_to_obsidian 的完整代码，无需改动) ...
    # 仅为了节省篇幅，这里略过，请直接复制昨天的逻辑
    # 记得最后 return full_path, doc_id  <-- 稍微改一下返回值，方便 pipeline 用
    
    category = raw_data.get("category", "文章阅读")
    url = raw_data.get("url", "")
    content = raw_data.get("content", "")
    
    doc_id = raw_data.get("doc_id") or (url_hash(url) if url else hashlib.md5(content.encode()).hexdigest())
    hash6 = doc_id[:6]
    
    title = ai_data.get("kb_title", raw_data.get("title", "无标题"))
    safe_title = sanitize_filename(title)
    
    now = time.localtime()
    year_month = time.strftime("%Y-%m", now)
    date_short = time.strftime("%m-%d", now)
    note_ts = time.strftime("%m-%d_%H%M", now)
    
    if category == "个人笔记":
        folder = "Notes"
        file_name = f"{note_ts}_{safe_title}__{hash6}.md"
    else:
        folder = "Articles"
        source = "其他"
        if "zhihu" in url: source = "知乎"
        elif "xiaohongshu" in url: source = "小红书"
        elif "weixin" in url: source = "公众号"
        elif raw_data.get("site"): source = raw_data.get("site")
        file_name = f"{source}-{date_short}-{safe_title}__{hash6}.md"

    dir_path = os.path.join(OBSIDIAN_ROOT, folder, year_month)
    os.makedirs(dir_path, exist_ok=True)
    full_path = os.path.join(dir_path, file_name)
    
    formatted_analysis = format_analysis_to_markdown(ai_data.get("analysis"))
    meta = {
        "created": time.strftime("%Y-%m-%d %H:%M", now),
        "source": url,
        "category": category,
        "tags": ai_data.get("tags", []),
        "kb_title": safe_title,
        "doc_id": doc_id,
        "url_hash": doc_id if url else ""
    }
    
    frontmatter = "\n".join([f"{k}: {json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v}" for k, v in meta.items()])
    callout = "💡 笔记整理" if category == "个人笔记" else "📖 AI 深度导读"
    
    md = f"---\n{frontmatter}\n---\n\n# {safe_title}\n\n> [!ABSTRACT] {callout}\n{formatted_analysis}\n\n---\n\n## 原文内容\n\n{content}\n"
    
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(md)
    
    print(f"💾 文件已保存: {full_path}")
    return full_path, doc_id  # <--- 注意：多返回了一个 doc_id


# === 4. 核心：保存到向量库 (Brain) ===
def save_to_vector_db(raw_data: dict, ai_data: dict, file_path: str, doc_id: str):
    """
    分块存入向量库，支持幂等更新（先删后写）
    """
    content = raw_data.get("content", "")
    if len(content) < MIN_CONTENT_LENGTH:
        print("⚠️ 内容太短，跳过向量化")
        return 0 # 返回插入数量

    title = ai_data.get("kb_title", "无标题")
    category = raw_data.get("category", "文章阅读")
    url = raw_data.get("url", "")
    
    # 1. 幂等清理：先删除旧的 (基于 metadata parent_id)
    # 这样如果文章更新了，旧的切片会被清除，不会有残留
    try:
        collection.delete(where={"parent_id": doc_id})
    except Exception:
        pass # 如果不存在也没关系

    # 2. 文本分块
    chunks = split_text_into_chunks(content)
    if not chunks:
        return 0

    # 3. 构造向量数据
    ids = []
    documents = []
    metadatas = []
    
    created_at = time.strftime("%Y-%m-%d %H:%M:%S")

    for i, chunk_text in enumerate(chunks):
        # 唯一 ID: 文档ID_块序号
        chunk_id = f"{doc_id}_{i}"
        
        meta = {
            "parent_id": doc_id,    # 关键：用于关联整篇文章
            "chunk_idx": i,
            "title": title,
            "category": category,
            "source": url,
            "file_path": file_path,
            "created_at": created_at
        }
        
        ids.append(chunk_id)
        documents.append(chunk_text)
        metadatas.append(meta)

    # 4. 批量写入 Chroma
    # 这里的 documents 会被自动 Embedding
    collection.upsert(
        ids=ids,
        documents=documents,
        metadatas=metadatas
    )
    
    print(f"🧠 向量化完成: {title} -> 切分 {len(chunks)} 块")
    return len(chunks)