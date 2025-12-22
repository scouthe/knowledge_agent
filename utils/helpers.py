import re
import hashlib
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

def sanitize_filename(title: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", title).strip()

def normalize_url(url: str) -> str:
    """规范化 URL，去除跟踪参数"""
    try:
        parts = urlsplit(url.strip())
        scheme = (parts.scheme or "https").lower()
        netloc = parts.netloc.lower()
        path = parts.path or "/"
        if path != "/" and path.endswith("/"):
            path = path[:-1]

        q = parse_qsl(parts.query, keep_blank_values=True)
        filtered = []
        drop_prefixes = ("utm_",)
        drop_keys = {"spm", "from", "source", "src", "share_source", "share_medium", "share_id"}
        for k, v in q:
            kl = k.lower()
            if any(kl.startswith(p) for p in drop_prefixes): continue
            if kl in drop_keys: continue
            filtered.append((k, v))
        query = urlencode(filtered, doseq=True)
        return urlunsplit((scheme, netloc, path, query, ""))
    except Exception:
        return url.strip()

def url_hash(url: str) -> str:
    nu = normalize_url(url)
    return hashlib.md5(nu.encode("utf-8")).hexdigest()