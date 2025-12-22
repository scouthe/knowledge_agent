import os

# === 基础路径 ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
INBOX_DIR = os.path.join(DATA_DIR, "inbox")
JOBS_LOG_PATH = os.path.join(DATA_DIR, "jobs.jsonl")
OBSIDIAN_ROOT = "/home/heheheh/Documents/obsidian" # 你的实际路径

# 自动创建必要目录
os.makedirs(INBOX_DIR, exist_ok=True)
os.makedirs(os.path.dirname(JOBS_LOG_PATH), exist_ok=True)

# === 企业微信配置 ===
CORP_ID = "wwa69b263cad69f601"
AGENT_ID = 1000002
CORP_SECRET = "qrC0S7tfy3ERlxZNLguu94XrM1KJdNeQhjMkRO67yUQ"
TOKEN = "Zjx3iRIbV1yzJRSB0ewMOOsESdUbO43R"
ENCODING_AES_KEY = "3NTSa7EenJNAWnB4TVKb6AoffEedjFjfbcxcd56h3xR"

# === LLM 配置 ===
LLM_API_URL = "http://192.168.1.148:1234/v1/chat/completions"
LLM_MODEL = "qwen2.5-14b-instruct"

# === 爬虫配置 ===
FAKE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
}
# 知乎 Cookie (太长了，建议后续放到环境变量或独立文件，这里先保留)
ZHIHU_COOKIE = "_xsrf=iN99nScvMyTmdjZxQcj3Qskno6oUKFfO; _zap=7bcf828e-1177-4dee-816d-7e00bf37aee1; d_c0=X-aTWDYJBRuPTn6prEbMryRFNXu-oAHNLqU=|1756974427; q_c1=6f05aa477862431696d6cf6af386a491|1760106311000|1760106311000; __zse_ck=004_jv5S/0hTb4g6PGx/Alxwift2T6GQJrNsxcszAiil39Wr3W6uqXAmtzeEbUa72hbyUKOzeQKQ=zNKK382OsvAMPVXurZxxd8HgLlguKEipCwNaCK3chyvoeyUf21=U3m/-d4pVsH78ABsQ2tLW1YKzDtt52twVH5MAV2VD6mMz/FIDdjyzYJU60lu6x2XrS//5VmTZVJ4z9ywPA1DfPtQ2M1zJJWIjIjE8Huxr2ngUYp+wuF/vMbUTtF6E+tMO1d2TxEhyivt0IA+wil0Eond/lGsncbMDS/44GTFBnOrpqig=; z_c0=2|1:0|10:1766233855|4:z_c0|92:Mi4xNzdSVEJnQUFBQUJmNXBOWU5na0ZHeVlBQUFCZ0FsVk5fLVF6YWdCNFFSdHNHa25xMDJRVGhidTQ1M3JVOURaT0h3|e480bca994b1742d81e6015779e217c09d5803ed0c1a1af8f845935497798d6b; Hm_lvt_98beee57fd2ef70ccdd5ca52b9740c49=1765714618,1765971061,1766233857,1766314304; HMACCOUNT=9EE3A55D00EDB050; SESSIONID=cwhfErJI2jYkjpH9lN8QcUxzuhHLxo3nGewVTuFaJFt; JOID=Wl4TBU1raDWxJD45NOlt73hPzR4hBh9d129Cc31XDGzaTkB_DVq5ctYkMDk0uDGUv7N_2Vpg3xbw1fkC3B8EvFM=; osd=VFERCkplZze-IzA2NuZq4XdNwhkvCR1S0GFNcXJQAmPYQUdxAli2ddgrMjYztj6WsLRx1lhv2Bj_1_YF0hAGs1Q=; Hm_lpvt_98beee57fd2ef70ccdd5ca52b9740c49=1766380476; BEC=92a0fca0e2e4d1109c446d0a990ad863" # 请填入你完整的 Cookie

# config.py
SQLITE_DB_PATH = os.path.join(DATA_DIR, "index.db")

# === RAG 配置 ===
CHROMA_DB_PATH = os.path.join(DATA_DIR, "chroma_db")
EMBEDDING_API_URL = "http://192.168.1.148:1234/v1"
# ⚠️ 必须填你 LM Studio 里加载的真实模型ID
EMBEDDING_MODEL_NAME = "text-embedding-bge-m3" 

CHROMA_COLLECTION_NAME = "knowledge_base"
MIN_CONTENT_LENGTH = 5  # 太短的内容不存向量库
CHUNK_SIZE = 800          # 每一块大约 800 字符
CHUNK_OVERLAP = 200       # 上下文重叠 200 字符

# === API 安全配置 ===
API_SECRET_KEY = "sk-123456" # 你自己随便设一个密码