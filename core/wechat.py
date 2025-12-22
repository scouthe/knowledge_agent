import time
import re
import httpx
from config import CORP_ID, CORP_SECRET, AGENT_ID

# 全局状态，Main 中也需要访问它
SYSTEM_STATE = {"error": False, "msg": ""}
token_cache = {"access_token": None, "expires_at": 0}

async def get_access_token():
    if token_cache["access_token"] and time.time() < token_cache["expires_at"]:
        return token_cache["access_token"]
    
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={CORP_ID}&corpsecret={CORP_SECRET}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        data = resp.json()
        if data.get("errcode") == 0:
            token_cache["access_token"] = data["access_token"]
            token_cache["expires_at"] = time.time() + 7000 
            return data["access_token"]
        return None

async def send_wecom_msg(user_id: str, content: str):
    global SYSTEM_STATE
    token = await get_access_token()
    if not token: return False
    
    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    payload = {
        "touser": user_id,
        "msgtype": "text",
        "agentid": AGENT_ID,
        "text": {"content": content},
        "safe": 0
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            res_data = resp.json()
            
            if res_data.get("errcode") == 60020:
                error_msg = res_data.get("errmsg", "")
                ip_match = re.search(r"from ip: ([\d\.]+)", error_msg)
                new_ip = ip_match.group(1) if ip_match else "未知"
                SYSTEM_STATE["error"] = True
                SYSTEM_STATE["msg"] = new_ip
                print(f"⚠️ IP 变动: {new_ip}")
                return False
            elif res_data.get("errcode") == 0:
                SYSTEM_STATE["error"] = False
                return True
    except Exception as e:
        print(f"❌ 发送通知出错: {e}")
    return False