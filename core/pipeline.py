import re
import time
import os
import hashlib
from utils.logger import append_job_event
from utils.helpers import url_hash
from core.crawler import fetch_via_trafilatura, fetch_via_jina
from core.llm import call_llm_analysis
from core.storage import save_to_obsidian, save_to_vector_db
from core.wechat import send_wecom_msg
# from core.index import save_to_keyword_index # 如有需要可取消注释

async def process_content_to_obsidian(job_id: str, content: str, user_id: str, mode: str = "auto"):
    t0 = time.time()
    append_job_event(job_id, "RUNNING", step="start", user_id=user_id)
    
    # === ✨ 修复点 1: 自动补全协议头 ===
    # 只有当用户明确指定 mode="crawl" 时才触发，防止误伤普通笔记
    if mode == "crawl" and not content.startswith(("http://", "https://")):
        # 简单判定：内容不包含空格（通常URL没空格），且包含点号（如 baidu.com）
        if " " not in content.strip() and "." in content:
            print(f"🔧 [Job {job_id}] 检测到缺少协议头，自动补全 https://")
            content = f"https://{content}"

    url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*'
    
    # === ✨ 修复点 2: 逻辑判断 ===
    if mode == "note":
        urls = [] # 强制清空 URL，不走爬虫分支
        print(f"📝 Job {job_id}: 用户指定为纯笔记模式，强制跳过 URL 解析")
    else:
        # 默认模式 ("auto" 或 "crawl") 才去解析 URL
        urls = re.findall(url_pattern, content)
        
    payload = {}
    target_url = ""

    # === 1. 抓取阶段 ===
    if urls:
        target_url = urls[0]
        use_jina = "xiaohongshu.com" in target_url or "xhslink.com" in target_url
        
        if not use_jina:
            append_job_event(job_id, "RUNNING", step="crawl_local", url=target_url)
            res = await fetch_via_trafilatura(target_url)
            if res: payload = res
            else: use_jina = True
            
        if use_jina:
            append_job_event(job_id, "RUNNING", step="crawl_jina", url=target_url)
            res = await fetch_via_jina(target_url)
            if res: 
                payload = res
                payload["category"] = "文章阅读"
            else:
                payload = {"type": "error", "msg": "抓取失败", "url": target_url}
        
        if payload.get("type") != "error":
            payload["doc_id"] = url_hash(target_url)
            
    else:
        # 个人笔记 (当 mode="note" 时，或者 mode="crawl" 但真的没输链接时走进这里)
        payload = {
            "type": "note",
            "category": "个人笔记",
            "content": content,
            "title": f"随手记_{content[:10].replace(chr(10), ' ')}",
            "doc_id": hashlib.md5(content.encode()).hexdigest()
        }

    # 错误熔断
    if payload.get("type") == "error":
        append_job_event(job_id, "FAILED", step="crawl", error=payload.get("msg"))
        await send_wecom_msg(user_id, f"❌ 入库失败: {payload.get('msg')}")
        return

    # === 2. AI 分析 ===
    try:
        # 如果是笔记，也可以让 AI 帮忙打标签或润色，这里保持原样调用
        ai_res = await call_llm_analysis(payload["content"], payload["category"])
    except Exception as e:
        await send_wecom_msg(user_id, f"⚠️ AI 失败: {e}")
        return

    # === 3. 保存 (双写模式) ===
    try:
        # A. 存文件 (Truth)
        path, doc_id = save_to_obsidian(payload, ai_res)
        
        # B. 存向量 (Brain)
        append_job_event(job_id, "RUNNING", step="save_vector_start", message="开始向量化...")
        
        chunk_count = save_to_vector_db(payload, ai_res, path, doc_id)
        
        append_job_event(job_id, "RUNNING", step="save_vector_success", 
                         message=f"向量化完成，切分 {chunk_count} 块",
                         extra={"chunk_count": chunk_count, "doc_id": doc_id})
        
    except Exception as e:
        await send_wecom_msg(user_id, f"⚠️ 保存失败: {e}")
        append_job_event(job_id, "FAILED", step="save_error", error=str(e))
        print(f"❌ 保存流程异常: {e}")
        return

    # === 4. 通知 ===
    try:
        file_name = os.path.basename(path)
        duration = round(time.time() - t0, 2)
        
        ok = await send_wecom_msg(user_id, f"✅ **入库成功**\n📄 {file_name}")
        status = "SUCCESS" if ok else "SUCCESS_NOTIFY_FAIL"
        
        append_job_event(job_id, status, step="done", message=f"耗时 {duration}s")
        print(f"✅ 任务结束 [耗时 {duration}s]: {file_name}")
    except Exception:
        pass