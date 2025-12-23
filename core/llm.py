import json
import httpx
import time
from config import LLM_API_URL, LLM_MODEL

async def call_llm_analysis(content: str, category: str):
    print(f"🧠 AI 分析中... [{category}]")
    
    if category == "个人笔记":
        instruction = "对笔记进行润色，返回 kb_title, summary, tags, analysis(核心想法/行动建议/关联概念)。"
    else:
        instruction = "对文章进行深度导读，返回 kb_title, summary, tags, analysis(背景/观点/结论)。"

    system_prompt = f"你是一个资深知识库管理员。请根据内容类型：{category}，严格以JSON格式返回结果。\n{instruction}\n不要包含Markdown标记。"

    payload = {
        "model": LLM_MODEL,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"内容：\n{content[:25000]}"}
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(LLM_API_URL, json=payload)
            resp.raise_for_status()
            raw = resp.json()['choices'][0]['message']['content']
            clean = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
    except Exception as e:
        print(f"❌ LLM 失败: {e}")
        return {
            "kb_title": f"未命名_{int(time.time())}",
            "summary": "AI 分析失败",
            "tags": ["AI_Error"],
            "analysis": f"错误: {str(e)}"
        }
    
def chat(user_query: str, system_prompt: str = "你是一个有用的助手。") -> str:
    """
    通用对话函数，供 Web UI (RAG) 使用
    """
    print(f"🤖 LLM 正在思考: {user_query[:20]}...")
    
    headers = {
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": LLM_MODEL, # 确保你的 config 里有 MODEL_NAME，没有的话写死字符串也可以
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query}
        ],
        "temperature": 0.7,
        "max_tokens": 2000,
        "stream": False
    }

    try:
        # 使用 httpx 发送请求 (复用之前的 LLM_API_URL)
        response = httpx.post(
            f"{LLM_API_URL}/v1/chat/completions", 
            headers=headers, 
            json=payload, 
            timeout=60.0 # RAG 检索阅读量大，超时设长一点
        )
        response.raise_for_status()
        
        # 解析返回结果
        result = response.json()
        answer = result['choices'][0]['message']['content']
        return answer

    except Exception as e:
        print(f"❌ Chat 接口调用失败: {e}")
        return f"抱歉，我的大脑（LLM）暂时连接不上。错误信息：{e}"