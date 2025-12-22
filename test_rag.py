import os
import chromadb
from chromadb.utils import embedding_functions
import httpx
import json
import re
import time
os.environ["CHROMA_ANONYMIZED_TELEMETRY"] = "False"

import chromadb
# 引入配置
from config import (
    CHROMA_DB_PATH, 
    CHROMA_COLLECTION_NAME, 
    EMBEDDING_API_URL, 
    EMBEDDING_MODEL_NAME,
    LLM_API_URL,
    LLM_MODEL
)

# === 1. 定义一个简单的会话状态类 ===
class ConversationSession:
    def __init__(self):
        self.history_doc_ids = []  # 存上一轮命中的文章 ID (Parent ID)
        self.last_topic = ""       # 存上一轮的主题（可选）

    def update(self, doc_ids, query):
        """更新锚点"""
        # 只保留唯一的文章 ID
        self.history_doc_ids = list(set(doc_ids))
        self.last_topic = query

    def clear(self):
        self.history_doc_ids = []
        self.last_topic = ""
        print("🧹 会话已重置")

# 初始化全局会话
session = ConversationSession()

def detect_intent_with_llm(query, last_topic):
    """
    使用 LLM 判断用户意图：是【开启新话题】还是【追问上一轮】
    """
    # 如果没有上一轮话题，肯定是新话题
    if not last_topic:
        return False
        
    print(f"🤔 正在分析意图... (上轮: {last_topic[:10]}...)")

    system_prompt = """
    你是一个对话意图分类器。
    任务：判断【当前问题】是否是针对【上轮话题】的追问或指代。
    
    输出规则：
    1. 如果是追问/指代/承接，只输出单词：TRUE
    2. 如果是全新的无关话题，只输出单词：FALSE
    
    示例：
    上轮：DeepSeek的优点
    当前：它怎么收费？ -> TRUE
    
    上轮：DeepSeek的优点
    当前：今天天气怎么样？ -> FALSE
    
    上轮：DeepSeek的优点
    当前：讲讲Qwen模型 -> FALSE (这是新实体)
    """
    
    user_prompt = f"上轮话题：{last_topic}\n当前问题：{query}"

    payload = {
        "model": LLM_MODEL,
        "temperature": 0.1, # 分类任务温度要低
        "max_tokens": 10,   # 只需要一个词
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    }

    try:
        resp = httpx.post(LLM_API_URL, json=payload, timeout=10)
        result = resp.json()['choices'][0]['message']['content'].strip().upper()
        
        # 只要 LLM 说是 TRUE，就是锚定模式
        is_follow_up = "TRUE" in result
        print(f"👉 意图判定结果: {'⚓️ 追问 (锚定)' if is_follow_up else '🌐 新话题 (全局)'}")
        return is_follow_up
        
    except Exception as e:
        print(f"⚠️ 意图识别失败，降级为全局搜索: {e}")
        return False

def is_follow_up_question(query):
    """
    简单启发式规则：判断是否是追问/指代
    规则：长度短，或包含代词
    """
    if len(query) < 10: return True
    triggers = ["他", "它", "这", "那", "其", "怎么用", "是谁", "继续", "深入"]
    return any(t in query for t in triggers)
# === [新增] 列举模式函数 ===
def handle_list_request(collection, query_text):
    """
    处理类似“有哪些文章”、“列出标题”的请求
    直接查元数据，不走向量搜索
    """
    # 简单的关键词判断，实际可以用 LLM 判断
    triggers = ["有哪些", "有什么", "列一下", "列出", "清单", "多少篇", "几个文章"]
    if not any(t in query_text for t in triggers) or "文章" not in query_text:
        return False

    print("📋 检测到【列举/统计】意图，正在查询元数据...")
    
    # 获取今天日期的前缀 (你的 metadata created_at 格式是 YYYY-MM-DD HH:MM:SS)
    today_str = time.strftime("%Y-%m-%d")
    
    # 直接从 Chroma 获取元数据 (limit 设大一点，比如 100)
    # 这是一个数据库查询操作，不是向量搜索
    results = collection.get(
        include=["metadatas"],
        limit=100 
    )
    
    metadatas = results['metadatas']
    
    # 过滤和去重
    unique_titles = set()
    today_count = 0
    
    for meta in metadatas:
        title = meta.get('title', '无标题')
        created_at = meta.get('created_at', '')
        
        # 将标题加入集合 (去重)
        unique_titles.add(title)
        
        # 统计今天的 (可选)
        if today_str in created_at:
            today_count += 1
            
    # 直接构造回答，不需要 LLM 思考 (或者也可以喂给 LLM 润色)
    print("-" * 50)
    print("🤖 系统直出结果:")
    print(f"\n📚 知识库当前已收录 {len(unique_titles)} 篇文章（切片总数: {len(metadatas)}）：\n")
    
    for i, title in enumerate(unique_titles, 1):
        print(f"{i}. 《{title}》")
        
    print(f"\n(注: 以上是全量列表，今日更新可能包含在内)")
    return True

def list_articles(filter_today=True):
    """
    快捷指令：列出文章
    filter_today=True: 只列出今天的
    filter_today=False: 列出所有
    """
    print("📋 正在读取知识库目录...")
    
    # 临时连接数据库
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    # 获取集合 (不需要 embedding function，因为只查元数据)
    collection = client.get_or_create_collection(name=CHROMA_COLLECTION_NAME)
    
    # 获取所有元数据
    results = collection.get(include=["metadatas"])
    metadatas = results['metadatas']
    
    if not metadatas:
        print("📭 知识库是空的。")
        return

    today_str = time.strftime("%Y-%m-%d")
    unique_titles = set()
    today_count = 0
    
    # 筛选逻辑
    for meta in metadatas:
        title = meta.get('title', '无标题')
        created_at = meta.get('created_at', '')
        
        # 如果只看今天，且日期不匹配，跳过
        if filter_today and today_str not in created_at:
            continue
            
        unique_titles.add(title)

    # 打印结果
    print("-" * 50)
    title_prefix = f"📅 【{today_str}】" if filter_today else "📚 【全量】"
    
    if not unique_titles:
        print(f"{title_prefix} 暂无收录文章。")
    else:
        print(f"{title_prefix} 已收录 {len(unique_titles)} 篇文章：\n")
        for i, title in enumerate(unique_titles, 1):
            print(f"{i}. 《{title}》")
            
    print("-" * 50)
def test_rag(query_text):
    global session
    
    # 手动重置指令
    if query_text.strip() == "/new":
        session.clear()
        return

    print(f"\n🔎 正在提问: 【{query_text}】")
    
    # 1. 连接向量库
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    emb_fn = embedding_functions.OpenAIEmbeddingFunction(
        api_key="lm-studio",
        api_base=EMBEDDING_API_URL,
        model_name=EMBEDDING_MODEL_NAME
    )
    collection = client.get_collection(name=CHROMA_COLLECTION_NAME, embedding_function=emb_fn)
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    collection = client.get_collection(name=CHROMA_COLLECTION_NAME, embedding_function=emb_fn)
    if handle_list_request(collection, query_text):
        return
    # === 2. 关键逻辑：AI 决定检索策略 ===
    search_kwargs = {
        "query_texts": [query_text],
        "n_results": 5
    }
    
    is_anchored = False
    
    # [修改点]：不再用 len() 或关键词，直接问 LLM
    # 只有当 session 里有东西，才需要判断是不是追问
    if session.history_doc_ids:
        # 传入：当前问题 + 上一轮的问题(作为话题背景)
        if detect_intent_with_llm(query_text, session.last_topic):
            print(f"⚓️ 触发锚定模式！锁定范围: {len(session.history_doc_ids)} 篇文章")
            search_kwargs["where"] = {"parent_id": {"$in": session.history_doc_ids}}
            is_anchored = True
        else:
            print("🌐 判定为新话题，进行全局检索")
            session.clear() # 清理旧状态
    else:
        print("🌐 全局检索模式 (无历史)")

    # 执行检索
    results = collection.query(**search_kwargs)

    # 结果解包
    documents = results['documents'][0]
    metadatas = results['metadatas'][0]
    distances = results['distances'][0]
    ids = results['ids'][0]

    if not documents:
        print("❌ 未找到相关内容")
        if is_anchored:
            print("🔄 尝试切换回全局搜索...")
            session.clear() # 清除上下文重试
            test_rag(query_text) # 递归调用一次
        return

    print(f"✅ 检索到 {len(documents)} 条相关切片:\n")
    
    # 收集这次命中的 parent_id，用于更新下一轮锚点
    current_doc_ids = []
    context_parts = []
    
    for i, doc in enumerate(documents):
        # 你的 metadata 里应该有 parent_id (对应整篇文章的 doc_id)
        # 如果没有 parent_id，用 doc_id 也行，取决于你 storage.py 怎么存的
        # 假设你昨天的代码存的是 parent_id
        p_id = metadatas[i].get('parent_id') 
        if p_id: current_doc_ids.append(p_id)
        
        chunk_id_short = ids[i].split('_')[-1]
        title = metadatas[i].get('title', '未知')
        dist = distances[i]
        
        print(f"🧩 [ID: {chunk_id_short}] (距离: {dist:.4f}) - {title}")
        context_parts.append(f"【参考片段 {i+1} (ID: {chunk_id_short})】\n{doc}")

    # === 3. 更新会话状态 ===
    # 只有在非锚定模式（新话题）下，才大幅更新 doc_ids
    # 如果是锚定模式，我们保持范围，或者取交集（这里简化为覆盖）
    if not is_anchored:
        session.update(current_doc_ids, query_text)
    
    # 4. 生成 (Generate)
    print("-" * 50)
    print("🤖 正在思考...")
    
    context_str = "\n\n".join(context_parts)
    
    # === [优化版] System Prompt ===
    
    # 基础人设
    base_prompt = """
    你是一个专业的知识库助手，负责根据检索到的片段回答用户问题。
    """
    
    # 锚定模式下的特殊指令
    if is_anchored:
        base_prompt += """
        背景：用户正在针对上文进行深入追问。
        任务：请综合【参考片段】中的信息，用通顺、逻辑清晰的语言回答。
        
        ⚠️ 关键修正要求：
        1. **人称转换**：如果原文使用第一人称（“我”、“笔者”），请改为第三人称描述（如“作者提到”、“文中指出”），不要让用户觉得是你在自述。
        2. **去除口语废话**：去掉原文中类似“如下图所示”、“大家看这里”等无法展示的视觉引导词。
        3. **总结而非复制**：不要机械抄写原文，请提取核心逻辑进行概括。
        """

    system_prompt = f"""
    {base_prompt}
    
    【参考片段】：
    {context_str}
    
    【回答规则】：
    1. 必须基于事实，严谨准确。
    2. 引用标注：在核心观点的句尾加上来源 ID，如 [ID: xxx]。
    3. 语气要自然、客观，像一个专业的分析师在介绍内容，而不是复读机。
    """
    
    # user_prompt 保持简单
    user_prompt = f"{query_text}"

    payload = {
        "model": LLM_MODEL,
        "temperature": 0.3, 
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    }

    try:
        resp = httpx.post(LLM_API_URL, json=payload, timeout=60)
        ai_answer = resp.json()['choices'][0]['message']['content']
        print(f"\n💡 AI 回答:\n{ai_answer}")
    except Exception as e:
        print(f"❌ LLM 调用失败: {e}")

if __name__ == "__main__":
    print("💡 提示:")
    print("  - 输入 'q' 退出")
    print("  - 输入 'l' 查看今天文章 (List Today)")
    print("  - 输入 'all' 查看所有文章")
    print("  - 输入 '/new' 重置对话上下文")
    
    while True:
        # 这里的 input 提示符可以简化一点
        q = input("\n🙋 请输入 (q/l/问题): ").strip()
        
        if not q: continue
        
        # === 快捷键监听 ===
        if q.lower() == 'q': 
            break
            
        elif q.lower() == 'l':
            # 触发今日列表
            list_articles(filter_today=True)
            continue # 跳过本次循环，不进入 test_rag
            
        elif q.lower() == 'all':
            # 触发全量列表
            list_articles(filter_today=False)
            continue
            
        # === 正常提问 ===
        test_rag(q)