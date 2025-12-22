# 🧠 Knowledge OS (璇玑枢)

**Knowledge OS** 是一个基于本地大模型（Local LLM）的个人知识库自动化管理系统。它集成了多渠道信息采集、AI 智能总结、Obsidian 知识库双向同步以及 RAG（检索增强生成）对话功能。

该项目坚持 **"Local First"** 原则，核心数据与模型计算全部在本地 GPU 服务器上完成，确保数据隐私与安全。

## ✨ 核心特性 (Key Features)

### 1. 全渠道信息采集 (Ingestion)

* **微信集成**：通过企业微信应用接口 + Cloudflare Tunnel 穿透，实现微信端直接转发文章链接入库。
* **多平台解析**：集成 `Trafilatura` 和 `Jina Reader`，支持知乎、小红书、微信公众号等主流平台正文提取。
* **Web 速记**：支持在网页端直接粘贴 URL 或记录灵感笔记。
* **文件投喂**：支持上传 PDF、Word、PPT 等文档，自动解析并转为 Markdown 入库。

### 2. AI 智能处理 (AI Processing)

* **本地大模型**：调用本地部署的 **Qwen2.5-14b-Instruct** 模型，对采集的内容进行自动总结、打标签和元数据生成。
* **语义向量化**：使用 **BGE-M3** 模型对长文本进行语义分块（Chunking）和向量化（Embedding）。

### 3. 双模存储架构 (Dual Storage)

* **文件层 (The Brain)**：所有内容以 Markdown 格式保存在本地 **Obsidian** 仓库中，所见即所得，方便二次编辑。
* **向量层 (The Hippocampus)**：切片后的向量数据存入 **ChromaDB**，用于支撑语义检索。

### 4. 交互式 Web 终端 (Streamlit UI)

* **知识阅览室**：可视化文件树（无限层级），支持按文件夹浏览、关键词搜索、阅读模式与编辑模式切换。
* **RAG 对话**：基于本地知识库的问答系统，支持多轮对话，回答附带原文引用来源（Source Attribution）。
* **数据治理**：提供“向量库同步”功能，自动检测并清理已删除文件的无效索引，消除幻觉。
* **系统监控**：可视化查看后端运行日志与任务队列状态。

---

## 🏗️ 系统架构 (Architecture)

```mermaid
graph TD
    User[用户] -->|微信转发/分享| WeCom[企业微信接口]
    User -->|Web上传/速记| WebUI[Streamlit 前端]
    
    WeCom -->|Cloudflare Tunnel| FastAPI[后端 API 服务]
    WebUI --> FastAPI
    
    subgraph "核心处理流 (Local Server)"
        FastAPI -->|放入队列| Worker[异步任务 Worker]
        Worker -->|解析 URL| Crawler[Trafilatura/Jina]
        Crawler -->|原文| LLM[Qwen2.5-14b (LM Studio)]
        LLM -->|总结/标签| MD_Gen[Markdown 生成器]
        
        MD_Gen -->|写入文件| Obsidian[Obsidian 仓库]
        MD_Gen -->|文本切片| Embed[BGE-M3 Embedding]
        Embed -->|存入索引| Chroma[ChromaDB 向量库]
    end
    
    subgraph "检索增强生成 (RAG)"
        WebUI -->|提问| Chroma
        Chroma -->|Top-K 片段| LLM
        LLM -->|生成回答| WebUI
    end

```

---

## 🛠️ 技术栈 (Tech Stack)

* **Language**: Python 3.11+
* **Web Framework**: Streamlit (Frontend), FastAPI (Backend)
* **Vector Database**: ChromaDB
* **LLM Inference**: LM Studio (Local Server)
* **Models**:
* LLM: `Qwen/Qwen2.5-14B-Instruct-GGUF`
* Embedding: `BAAI/bge-m3`


* **Tools**:
* `Trafilatura` / `Jina Reader` (Web Scraping)
* `WeChatPy` (WeChat Integration)
* `MarkItDown` (Document Parsing)
* `Cloudflared` (Intranet Penetration)


* **Hardware**: Dual NVIDIA RTX 4070 Ti (24GB VRAM Total)

---

## 🚀 快速开始 (Getting Started)

### 前置要求

1. 安装 **Conda** 环境。
2. 安装并配置 **LM Studio**，加载 Qwen2.5 模型并开启 Local Server (Port 1234)。
3. 拥有一个 **Obsidian** 仓库路径。
4. 配置 **Cloudflare Tunnel** 指向本地 8888 端口（用于微信回调）。

### 1. 安装依赖

```bash
conda create -n agent_env python=3.11
conda activate agent_env
pip install -r requirements.txt
# 安装 MarkItDown 的完整依赖
pip install "markitdown[all]"
pip install torch sentence-transformers

系统级依赖 (Linux): 为了让 MarkItDown 或 Trafilatura 更好地处理某些复杂格式，建议在 Ubuntu 上安装一些基础工具库（如果还没装的话）：
sudo apt-get update
sudo apt-get install -y ffmpeg libsm6 libxext6  # 处理图片/视频可能需要

```

### 2. 配置文件 (`config.py`)

请复制 `config_sample.py` 为 `config.py` 并填入以下信息：

```python
# 路径配置
OBSIDIAN_ROOT = "/path/to/your/obsidian/vault"
CHROMA_PATH = "./chroma_db"

# LLM 配置
LLM_API_URL = "http://localhost:1234/v1"
LLM_MODEL = "qwen2.5-14b-instruct"

# 微信/鉴权配置
TOKEN = "your_wechat_token"
ENCODING_AES_KEY = "your_aes_key"
CORP_ID = "your_corp_id"
API_SECRET_KEY = "your_custom_secret_key"

```

### 3. 启动服务

**方式一：手动启动 (开发调试)**

```bash
# 终端 1: 启动后端
python main.py

# 终端 2: 启动前端
streamlit run web_ui.py

```

**方式二：Systemd 托管 (生产模式)**

```bash
sudo systemctl start knowledge-backend
sudo systemctl start knowledge-frontend

```

---

## 📂 项目结构

```text
knowledge_agent/
├── core/
│   ├── pipeline.py       # 核心处理流：抓取->总结->入库
│   └── wechat.py         # 微信消息处理逻辑
├── utils/
│   ├── inbox.py          # 任务队列管理
│   ├── logger.py         # 日志记录模块
│   └── vector.py         # 向量库操作封装
├── web_ui.py             # Streamlit 前端界面代码
├── main.py               # FastAPI 后端入口 & Worker
├── config.py             # 配置文件
├── requirements.txt      # 依赖列表
└── README.md             # 项目说明

```

---

## 📝 待办事项 (Roadmap)

* [x] 基础 RAG 对话与来源引用
* [x] 多平台文章自动采集与总结
* [x] 向量库与文件系统同步清理
* [ ] **多模态支持**：图片 OCR 与 视频内容理解
* [ ] **语音速记**：集成 Whisper 实现语音转文字笔记
* [ ] **高级 RAG**：引入 Query Rewrite (查询重写) 与 Rerank (重排序)
* [ ] **非微信源**：Telegram/Slack Bot 集成

---

