# test_embedding.py
import httpx
import json

# 修改为你的 LM Studio 配置
API_URL = "http://192.168.1.148:1234/v1/embeddings"
MODEL_NAME = "text-embedding-bge-m3" # 你的模型名

def test_embedding():
    print(f"📡 正在测试 Embedding 接口: {API_URL}")
    print(f"🤖 模型: {MODEL_NAME}")
    
    payload = {
        "input": "测试文本",
        "model": MODEL_NAME
    }
    
    try:
        resp = httpx.post(API_URL, json=payload, timeout=10)
        print(f"Status Code: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            # 检查返回结构是否符合 OpenAI 标准
            if "data" in data and len(data["data"]) > 0:
                vec = data["data"][0]["embedding"]
                print(f"✅ 成功! 向量维度: {len(vec)}")
                print(f"向量预览: {vec[:5]}...")
                return True
            else:
                print(f"❌ 返回格式异常: {data}")
        else:
            print(f"❌ 请求失败: {resp.text}")
            
    except Exception as e:
        print(f"❌ 连接错误: {e}")
        print("请检查 LM Studio Server 是否开启，且 'Text Embedding' 选项已勾选。")

if __name__ == "__main__":
    test_embedding()