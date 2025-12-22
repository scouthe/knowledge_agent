import httpx
import trafilatura
from utils.helpers import sanitize_filename
from config import FAKE_HEADERS, ZHIHU_COOKIE

async def fetch_via_jina(url: str):
    """Jina Reader 抓取"""
    print(f">>> Jina 抓取: {url}")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"https://r.jina.ai/{url}")
            if resp.status_code == 200:
                content = resp.text
                if len(content) < 10: return None
                
                lines = content.split('\n')
                title = lines[0].replace('# ', '').strip() if lines and lines[0].startswith('# ') else "Jina抓取"
                
                return {
                    "type": "article",
                    "title": sanitize_filename(title),
                    "content": content,
                    "url": url,
                    "author": "Jina Reader",
                    "site": "WebClip"
                }
    except Exception as e:
        print(f"❌ Jina 错误: {e}")
    return None

async def fetch_via_trafilatura(url: str):
    """本地抓取"""
    headers = FAKE_HEADERS.copy()
    if "zhihu.com" in url: headers["Cookie"] = ZHIHU_COOKIE
    
    try:
        async with httpx.AsyncClient(verify=False, follow_redirects=True, timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                text = trafilatura.extract(resp.text, output_format="markdown", include_images=True, include_formatting=True, include_links=True)
                meta = trafilatura.extract_metadata(resp.text)
                if text and len(text) > 100 and "安全验证" not in text:
                     return {
                        "type": "article",
                        "category": "文章阅读",
                        "title": sanitize_filename(meta.title if meta else "无标题"),
                        "content": text,
                        "url": url,
                        "author": meta.author if meta else "",
                        "site": meta.sitename if meta else ""
                    }
    except Exception:
        pass
    return None