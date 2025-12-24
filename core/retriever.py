# core/retriever.py
from core.storage import collection as chroma_collection
from core.index import search_keywords

def hybrid_search(query: str, top_k=5, user_id: str | None = None):
    """
    混合检索：向量(语义) + 关键词(精确) -> RRF合并
    """
    print(f"🔍 正在进行混合检索: {query}")
    
    # 1. 向量检索 (找意思相近的)
    vec_res = chroma_collection.query(
        query_texts=[query],
        n_results=top_k*2,
        include=["documents", "metadatas", "distances"],
    )
    vec_docs = []
    if vec_res['ids']:
        for i, doc_id in enumerate(vec_res['ids'][0]):
            meta = vec_res.get("metadatas", [[]])[0][i] if vec_res.get("metadatas") else {}
            if user_id and (meta.get("user_id") != user_id):
                continue
            vec_docs.append({
                "doc_id": doc_id, 
                "content": vec_res['documents'][0][i], 
                "rank": i + 1 # 排名 1, 2, 3...
            })
            
    # 2. 关键词检索 (找字面匹配的)
    kw_res = search_keywords(query, top_k=top_k*2, user_id=user_id)
    kw_docs = []
    for i, item in enumerate(kw_res):
        kw_docs.append({
            "doc_id": item['doc_id'],
            "content": item['content'],
            "rank": i + 1
        })
        
    # 3. RRF 融合打分 (倒数排名融合)
    # score = 1 / (60 + rank)
    final_scores = {}
    doc_content_map = {} # 临时存内容
    
    # 处理向量结果
    for item in vec_docs:
        did = item['doc_id']
        doc_content_map[did] = item['content']
        final_scores[did] = final_scores.get(did, 0) + (1 / (60 + item['rank']))
        
    # 处理关键词结果
    for item in kw_docs:
        did = item['doc_id']
        doc_content_map[did] = item['content']
        final_scores[did] = final_scores.get(did, 0) + (1 / (60 + item['rank']))
        
    # 4. 排序并返回 Top K
    sorted_ids = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    
    final_results = []
    for did, score in sorted_ids:
        final_results.append({
            "doc_id": did,
            "content": doc_content_map[did],
            "score": score
        })
        
    return final_results
