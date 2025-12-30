import base64
import hashlib
import json
import os
import time
from typing import Any

import httpx
from PIL import Image, ExifTags

from config import VLM_API_URL, VLM_MODEL, IMAGE_OCR_ARTICLE_THRESHOLD
from utils.helpers import sanitize_filename


def _extract_exif(path: str) -> dict[str, Any]:
    shot_time = ""
    gps = ""
    try:
        with Image.open(path) as img:
            exif = img._getexif() or {}
        tags = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
        shot_time = tags.get("DateTimeOriginal") or tags.get("DateTime") or ""

        gps_info = tags.get("GPSInfo")
        if gps_info:
            gps_tags = {ExifTags.GPSTAGS.get(k, k): v for k, v in gps_info.items()}
            lat = _gps_to_deg(gps_tags.get("GPSLatitude"), gps_tags.get("GPSLatitudeRef"))
            lon = _gps_to_deg(gps_tags.get("GPSLongitude"), gps_tags.get("GPSLongitudeRef"))
            if lat is not None and lon is not None:
                gps = f"{lat:.6f},{lon:.6f}"
    except Exception:
        pass
    return {"shot_time": shot_time, "gps": gps}


def _gps_to_deg(value, ref):
    if not value or not ref:
        return None
    try:
        d = value[0][0] / value[0][1]
        m = value[1][0] / value[1][1]
        s = value[2][0] / value[2][1]
        deg = d + (m / 60.0) + (s / 3600.0)
        if ref in ("S", "W"):
            deg = -deg
        return deg
    except Exception:
        return None


def _call_vlm(image_path: str) -> dict[str, Any]:
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    prompt = (
        "请分析这张图片并只输出 JSON，字段如下：\n"
        "description: 图片内容描述（中文）\n"
        "ocr_text: 图片中的文字（如没有则空字符串）\n"
        "is_text_heavy: 是否为文字/文章类图片（true/false）\n"
        "要求：只输出 JSON，不要加任何解释。"
    )

    payload = {
        "model": VLM_MODEL,
        "messages": [
            {"role": "system", "content": "你是一个严谨的多模态图像分析助手。"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                ],
            },
        ],
        "temperature": 0.2,
        "max_tokens": 800,
    }

    resp = httpx.post(VLM_API_URL, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"].strip()

    return _safe_json(content)


def _safe_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            pass
    return {"description": "", "ocr_text": "", "is_text_heavy": False}


def analyze_image(path: str) -> dict[str, Any]:
    exif = _extract_exif(path)
    vlm = _call_vlm(path)

    ocr_text = (vlm.get("ocr_text") or "").strip()
    is_text_heavy = bool(vlm.get("is_text_heavy")) or len(ocr_text) >= IMAGE_OCR_ARTICLE_THRESHOLD

    return {
        "shot_time": exif.get("shot_time", ""),
        "gps": exif.get("gps", ""),
        "description": (vlm.get("description") or "").strip(),
        "ocr_text": ocr_text,
        "is_text_heavy": is_text_heavy,
    }


def build_image_filename(image_bytes: bytes, text: str | None) -> str:
    seed = image_bytes + (text.encode("utf-8") if text else b"")
    return hashlib.md5(seed).hexdigest()


def build_title(text: str, description: str) -> str:
    if text:
        return sanitize_filename(text.strip()[:20]) or "图片笔记"
    if description:
        return sanitize_filename(description.strip()[:20]) or "图片记录"
    return "图片记录"


def build_markdown(
    *,
    title: str,
    created: str,
    category: str,
    doc_id: str,
    user_id: str,
    image_rel_path: str,
    shot_time: str,
    gps: str,
    text: str,
    description: str,
    ocr_text: str,
    folder: str,
) -> str:
    meta = {
        "created": created,
        "category": category,
        "kb_title": title,
        "doc_id": doc_id,
        "user_id": user_id,
        "folder": folder,
        "text_len": len(text),
        "image_path": image_rel_path,
        "image_shot_time": shot_time,
        "image_gps": gps,
        "image_location": gps,
        "image_desc": description,
        "ocr_chars": len(ocr_text),
    }
    frontmatter = "\n".join([f"{k}: {v}" for k, v in meta.items()])

    parts = [
        f"---\n{frontmatter}\n---\n",
        f"# {title}\n",
    ]
    if text:
        parts.append("## 用户文字\n")
        parts.append(text.strip() + "\n")
    parts.append("## 图片\n")
    parts.append(f"![[{image_rel_path}]]\n")
    if description:
        parts.append("## 图片描述\n")
        parts.append(description + "\n")
    if ocr_text:
        parts.append("## OCR\n")
        parts.append(ocr_text + "\n")
    return "\n".join(parts).strip() + "\n"
