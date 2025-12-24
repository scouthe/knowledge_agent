# core/index.py
import sqlite3
import jieba # 需要 pip install jieba 做中文分词
from config import SQLITE_DB_PATH

TABLE_V1 = "articles_fts"
TABLE_V2 = "articles_fts_v2"

def _table_exists(conn, name: str) -> bool:
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return c.fetchone() is not None

def init_db():
    conn = sqlite3.connect(SQLITE_DB_PATH)
    c = conn.cursor()
    # 创建 FTS5 虚拟表，支持全文检索
    # content_jieba 存分词后的文本，用于搜索
    c.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts 
        USING fts5(doc_id, title, content, content_jieba, created_at, category, tags)
    ''')
    c.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts_v2 
        USING fts5(doc_id, title, content, content_jieba, created_at, category, tags, user_id)
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
    user_id = raw_data.get("user_id", "")
    
    # 中文分词 (FTS5 默认对中文支持不好，需要手动分词)
    content_jieba = " ".join(jieba.cut(content))
    
    # 覆盖写入 (删除旧的 -> 插入新的)
    if _table_exists(conn, TABLE_V2):
        c.execute(f"DELETE FROM {TABLE_V2} WHERE doc_id = ?", (doc_id,))
        c.execute(f'''
            INSERT INTO {TABLE_V2} (doc_id, title, content, content_jieba, created_at, category, tags, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (doc_id, title, content, content_jieba, created_at, category, tags, user_id))
    if _table_exists(conn, TABLE_V1):
        c.execute(f"DELETE FROM {TABLE_V1} WHERE doc_id = ?", (doc_id,))
        c.execute(f'''
            INSERT INTO {TABLE_V1} (doc_id, title, content, content_jieba, created_at, category, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (doc_id, title, content, content_jieba, created_at, category, tags))
    
    conn.commit()
    conn.close()
    print(f"📇 关键词索引已更新: {doc_id[:6]}")

def search_keywords(query: str, top_k=10, user_id: str | None = None):
    """BM25 关键词检索"""
    conn = sqlite3.connect(SQLITE_DB_PATH)
    c = conn.cursor()
    
    query_jieba = " ".join(jieba.cut(query))
    
    results = []
    if _table_exists(conn, TABLE_V2):
        if user_id:
            c.execute(f'''
                SELECT doc_id, content, rank 
                FROM {TABLE_V2} 
                WHERE {TABLE_V2} MATCH ? AND user_id = ?
                ORDER BY rank 
                LIMIT ?
            ''', (query_jieba, user_id, top_k))
        else:
            c.execute(f'''
                SELECT doc_id, content, rank 
                FROM {TABLE_V2} 
                WHERE {TABLE_V2} MATCH ? 
                ORDER BY rank 
                LIMIT ?
            ''', (query_jieba, top_k))
        results = [{"doc_id": row[0], "content": row[1], "score": row[2]} for row in c.fetchall()]
    elif _table_exists(conn, TABLE_V1):
        c.execute(f'''
            SELECT doc_id, content, rank 
            FROM {TABLE_V1} 
            WHERE {TABLE_V1} MATCH ? 
            ORDER BY rank 
            LIMIT ?
        ''', (query_jieba, top_k))
        results = [{"doc_id": row[0], "content": row[1], "score": row[2]} for row in c.fetchall()]

    conn.close()
    return results

# 初始化
init_db()
