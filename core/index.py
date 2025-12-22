# core/index.py
import sqlite3
import jieba # 需要 pip install jieba 做中文分词
from config import SQLITE_DB_PATH

def init_db():
    conn = sqlite3.connect(SQLITE_DB_PATH)
    c = conn.cursor()
    # 创建 FTS5 虚拟表，支持全文检索
    # content_jieba 存分词后的文本，用于搜索
    c.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts 
        USING fts5(doc_id, title, content, content_jieba, created_at, category, tags)
    ''')
    conn.commit()
    conn.close()

def save_to_keyword_index(raw_data: dict, ai_data: dict):
    """写入 SQLite FTS 索引"""
    conn = sqlite3.connect(SQLITE_DB_PATH)
    c = conn.cursor()
    
    doc_id = raw_data.get("doc_id")
    title = ai_data.get("kb_title", "")
    content = raw_data.get("content", "")
    created_at = raw_data.get("created_at", "") # 需要在 pipeline 里补全这个字段
    category = raw_data.get("category", "")
    tags = ",".join(ai_data.get("tags", []))
    
    # 中文分词 (FTS5 默认对中文支持不好，需要手动分词)
    content_jieba = " ".join(jieba.cut(content))
    
    # 覆盖写入 (删除旧的 -> 插入新的)
    c.execute("DELETE FROM articles_fts WHERE doc_id = ?", (doc_id,))
    c.execute('''
        INSERT INTO articles_fts (doc_id, title, content, content_jieba, created_at, category, tags)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (doc_id, title, content, content_jieba, created_at, category, tags))
    
    conn.commit()
    conn.close()
    print(f"📇 关键词索引已更新: {doc_id[:6]}")

def search_keywords(query: str, top_k=10):
    """BM25 关键词检索"""
    conn = sqlite3.connect(SQLITE_DB_PATH)
    c = conn.cursor()
    
    query_jieba = " ".join(jieba.cut(query))
    
    # SQLite FTS5 默认按 BM25 排序
    # bm25(articles_fts) 是内置排序函数
    c.execute('''
        SELECT doc_id, content, rank 
        FROM articles_fts 
        WHERE articles_fts MATCH ? 
        ORDER BY rank 
        LIMIT ?
    ''', (query_jieba, top_k))
    
    results = [{"doc_id": row[0], "content": row[1], "score": row[2]} for row in c.fetchall()]
    conn.close()
    return results

# 初始化
init_db()