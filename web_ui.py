import streamlit as st
import os
import chromadb
import httpx
import time
import datetime
import json
import tempfile
from chromadb.utils import embedding_functions

# === 1. 配置引入 (适配你的 Config) ===
from config import (
    CHROMA_DB_PATH,        # 确保 config.py 里是 CHROMA_PATH
    CHROMA_COLLECTION_NAME,
    LLM_API_URL,
    LLM_MODEL,
    OBSIDIAN_ROOT,
    EMBEDDING_MODEL_NAME,
    JOBS_LOG_PATH       # 确保 config.py 里有 JOBS_LOG_PATH = "logs/jobs.jsonl"
)

# === 2. 页面初始化 ===
st.set_page_config(page_title="Knowledge OS", page_icon="🧠", layout="wide")

# === 3. 初始化数据库连接 ===
@st.cache_resource
def get_vector_store():
    """初始化数据库连接"""
    try:
        client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        emb_fn = embedding_functions.OpenAIEmbeddingFunction(
            api_key="lm-studio",
            api_base=LLM_API_URL, 
            model_name=EMBEDDING_MODEL_NAME  
        )
        collection = client.get_or_create_collection(
            name=CHROMA_COLLECTION_NAME, 
            embedding_function=emb_fn
        )
        return collection
    except Exception as e:
        st.error(f"❌ 数据库连接失败: {e}")
        return None

collection = get_vector_store()

# === 4. 核心逻辑函数 (保留原版高级逻辑) ===

def detect_intent_with_llm(query, last_topic):
    """使用 LLM 判断是否是追问"""
    if not last_topic: return False
    
    system_prompt = "你是一个对话意图分类器。判断【当前问题】是否是针对【上轮话题】的追问。如果是追问/指代，输出TRUE；否则输出FALSE。"
    user_prompt = f"上轮话题：{last_topic}\n当前问题：{query}"
    
    payload = {
        "model": LLM_MODEL,
        "temperature": 0.1,
        "max_tokens": 10,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    }
    
    try:
        resp = httpx.post(LLM_API_URL, json=payload, timeout=10)
        result = resp.json()['choices'][0]['message']['content'].strip().upper()
        return "TRUE" in result
    except:
        return False

def check_is_list_request(query):
    """判断是否是查询列表"""
    triggers = ["有哪些", "有什么", "列一下", "列出", "清单", "多少篇", "list"]
    return any(t in query for t in triggers) and ("文章" in query or "笔记" in query)

def get_article_list(filter_today=False):
    """获取文章列表字符串"""
    if not collection: return "数据库未连接"
    try:
        results = collection.get(include=["metadatas"], limit=100)
        metadatas = results['metadatas']
        today_str = time.strftime("%Y-%m-%d")
        unique_titles = set()
        
        for meta in metadatas:
            title = meta.get('title', '无标题')
            created_at = meta.get('created_at', '')
            if filter_today and today_str not in created_at:
                continue
            unique_titles.add(title)
            
        if not unique_titles:
            return "📭 暂时没有找到文章。"
        
        response = f"📚 **共找到 {len(unique_titles)} 篇文章**：\n\n"
        for i, title in enumerate(unique_titles, 1):
            response += f"{i}. 《{title}》\n"
        return response
    except Exception as e:
        return f"查询出错: {e}"

# === 5. Session State 初始化 ===
if "messages" not in st.session_state:
    st.session_state.messages = []
if "history_doc_ids" not in st.session_state:
    st.session_state.history_doc_ids = []
if "last_topic" not in st.session_state:
    st.session_state.last_topic = ""

# === 6. 页面路由 ===
page_mode = st.sidebar.radio("模式选择", ["对话/阅读", "🖥️ 系统日志"])

# --- 页面 A: 系统日志 ---
if page_mode == "🖥️ 系统日志":
    st.title("🖥️ 系统运行日志")
    if st.button("🔄 刷新日志"): st.rerun()

    if os.path.exists(JOBS_LOG_PATH):
        logs = []
        try:
            with open(JOBS_LOG_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()[-30:][::-1] # 取最后30条
                for line in lines:
                    if not line.strip(): continue
                    try: logs.append(json.loads(line))
                    except: logs.append({"raw": line})
        except Exception as e:
            st.error(f"读取日志失败: {e}")
            st.stop()

        for log in logs:
            if "raw" in log:
                st.text(log["raw"])
                continue
                
            ts = log.get("ts", "")
            try:
                time_str = datetime.datetime.fromisoformat(ts).strftime("%H:%M:%S")
            except: time_str = ts

            status = log.get("status", "UNKNOWN")
            message = log.get("message", "")
            step = log.get("step", "")
            job_id = log.get("job_id", "")[-4:]
            
            if "FAIL" in status: color, icon = "red", "❌"
            elif "SUCCESS" in status: color, icon = "green", "✅"
            elif "RUNNING" in status: color, icon = "blue", "🔵"
            else: color, icon = "gray", "ℹ️"

            with st.expander(f"{icon} [{time_str}] {message} (Step: {step})"):
                st.markdown(f"**Status**: :{color}[{status}] | **Job ID**: `...{job_id}`")
                if log.get("extra"): st.json(log["extra"])
    else:
        st.warning(f"📭 暂无日志文件: {JOBS_LOG_PATH}")
    
    st.stop() # 停止渲染下面的聊天界面

# --- 页面 B: 对话/阅读 (主界面) ---

# === 侧边栏 UI ===
with st.sidebar:
    # 1. 开发计划 (保留原版)
    with st.expander("📌 开发计划 (TODO List)", expanded=False):
            st.markdown("#### 🔌 数据源 & 格式")
            st.checkbox("寻找非企业微信入库接口 (Telegram/Slack/Email)", value=False)
            st.checkbox("多模态支持：图片/视频的 OCR 与内容理解 (VLM)", value=False)
            st.checkbox("速记接口没办法准确识别链接和笔记，笔记中有链接就直接获取链接了。", value=False)
            st.checkbox("增加手动打标签功能，以及代办完成，标签从待观看，待完成改为完成这种功能", value=False)
            st.checkbox("🎙️ 语音速记：集成 Whisper 实现本地语音转文字入库", value=False)
            st.markdown("#### 🧠 算法 & RAG 优化")
            st.checkbox("智能保存：LLM 重写摘要/标签 + 自动更新 Frontmatter", value=False)
            st.checkbox("Query Rewrite：多轮对话下的搜索语句重写", value=False)
            st.checkbox("Rerank 重排序：引入 Cross-Encoder 提升 Top-K 准确率", value=False)
            st.checkbox("🔪 语义切片：基于 Markdown 标题结构的智能分块 (非暴力截断)", value=False)
            st.checkbox("🕸️ Graph RAG：利用 Obsidian 双链 `[[Link]]` 增强检索上下文", value=False)
    
    st.divider()
    st.title("🧠 Knowledge OS")
    
    # 2. 快捷指令区
    st.subheader("⚡ 快捷指令")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("🗑️ 重开", use_container_width=True):
            st.session_state.messages = []
            st.session_state.history_doc_ids = []
            st.session_state.last_topic = ""
            if "clicked_file_name" in st.session_state: del st.session_state.clicked_file_name
            st.rerun()
    with c2:
        if st.button("📅 今日", use_container_width=True):
            st.session_state.messages.append({"role": "user", "content": "列出今日文章"})
            st.session_state.messages.append({"role": "assistant", "content": get_article_list(True)})
            st.rerun()
    with c3:
        if st.button("🧹 整理", use_container_width=True):
            with st.spinner("清理中..."):
                try:
                    res = httpx.post("http://localhost:8888/prune", timeout=30)
                    st.toast(f"清理: {res.json().get('deleted_chunks', 0)} 条")
                except: st.error("后端未连接")

    # 3. ✨ 速记/存链接 (已集成新版轮询逻辑) ✨
    with st.expander("📥 速记 / 存链接", expanded=True):
        with st.form("ingest_form", clear_on_submit=True):
            note_content = st.text_area("内容", placeholder="输入笔记或URL...", height=120, label_visibility="collapsed")
            b1, b2 = st.columns(2)
            with b1: sub_note = st.form_submit_button("📝 仅存笔记", use_container_width=True)
            with b2: sub_url = st.form_submit_button("🌐 抓取网页", use_container_width=True)
            
            if (sub_note or sub_url) and note_content.strip():
                mode = "note" if sub_note else "crawl"
                try:
                    # 发送请求
                    resp = httpx.post("http://localhost:8888/ingest", 
                                      json={"user_id": "web", "content": note_content, "mode": mode}, 
                                      timeout=5)
                    
                    if resp.status_code == 200:
                        job_id = resp.json().get("job_id")
                        
                        # 轮询状态
                        with st.status("🚀 任务提交成功，处理中...", expanded=True) as status_box:
                            st.write(f"Job ID: `{job_id}`")
                            
                            # ✨ 关键变量：记录上一步的状态，用于去重
                            last_step_seen = None 
                            
                            for _ in range(40): # 等待 60s
                                time.sleep(1.5)
                                # --- 核心修复开始 ---
                                # 1. 初始化变量，防止 try 失败后变量未定义
                                info = {}
                                status = "UNKNOWN"
                                step = ""
                                
                                try:
                                    r_stat = httpx.get(f"http://localhost:8888/api/status/{job_id}", timeout=3)
                                    if r_stat.status_code == 200:
                                        info = r_stat.json()
                                        status = info.get("status")
                                        step = info.get("step")
                                except Exception: 
                                    # ⚠️ 只能捕获 Exception，绝对不能写 bare except (即不能写 "except:")
                                    # 否则会把 st.rerun() 的中断信号也吞掉！
                                    pass

                                # 2. 更新显示逻辑 (放在 try 外面更安全)
                                if step and step != last_step_seen:
                                    step_map = {
                                        "worker_pick": "工人接单",
                                        "crawl_local": "本地爬虫抓取",
                                        "crawl_jina": "云端 Jina 解析",
                                        "save_vector_start": "开始向量化",
                                        "save_vector_success": "向量化完成",
                                        "done": "全部完成"
                                    }
                                    display_step = step_map.get(step, step)
                                    st.write(f"🔄 {display_step}...")
                                    last_step_seen = step

                                # 3. 判断结束条件
                                if status and "SUCCESS" in status:
                                    status_box.update(label="✅ 处理完成！", state="complete", expanded=False)
                                    
                                    if status == "SUCCESS_NOTIFY_FAIL":
                                        st.warning(f"入库成功，但微信通知失败: {info.get('message')}")
                                    else:
                                        st.success(f"成功: {info.get('message')}")
                                    
                                    # 给用户 1 秒钟看一眼成功的提示
                                    time.sleep(1)
                                    # 🚀 这行代码现在能正常工作了，因为它在 try...except 之外
                                    st.rerun() 
                                    
                                elif status and "FAIL" in status:
                                    status_box.update(label="❌ 失败", state="error")
                                    st.error(info.get("error"))
                                    # 失败了通常不需要 rerun，停在这里让用户看报错
                                    break
                            else:
                                status_box.update(label="⚠️ 后台运行中 (请稍后在阅览室查看)", state="running")
                except Exception as e:
                    st.error(f"连接失败: {e}")

    # 4. 文件投喂 (MarkItDown)
    with st.expander("📂 投喂文档 (PDF/Office)", expanded=False):
        uploaded_file = st.file_uploader("上传文件", type=["pdf", "docx", "pptx", "xlsx"])
        if uploaded_file and st.button("🚀 解析入库", use_container_width=True):
            with st.spinner("解析中..."):
                try:
                    from markitdown import MarkItDown
                    suffix = "." + uploaded_file.name.split('.')[-1]
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(uploaded_file.getvalue())
                        tmp_path = tmp.name
                    
                    md = MarkItDown().convert(tmp_path).text_content
                    clean_name = uploaded_file.name.rsplit('.', 1)[0]
                    save_name = f"{time.strftime('%Y%m%d_%H%M%S')}_{clean_name}.md"
                    inbox_path = os.path.join(OBSIDIAN_ROOT, "Inbox")
                    if not os.path.exists(inbox_path): os.makedirs(inbox_path)
                    
                    with open(os.path.join(inbox_path, save_name), "w", encoding="utf-8") as f:
                        f.write(f"---\ntitle: {clean_name}\ntype: upload\n---\n\n{md}")
                    
                    # 触发后端
                    httpx.post("http://localhost:8888/ingest", 
                               json={"user_id": "upload", "content": f"上传文件: {clean_name}\n{md[:500]}...", "mode": "note"})
                    st.success(f"✅ 已存入 Inbox")
                    os.remove(tmp_path)
                except Exception as e:
                    st.error(f"解析失败: {e}")

    st.divider()

    # 5. 📂 阅览室 (保留原版树状图)
    st.subheader("📂 阅览室")
    
    # 扫描文件
    all_files = []
    if os.path.exists(OBSIDIAN_ROOT):
        for root, dirs, files in os.walk(OBSIDIAN_ROOT):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for name in files:
                if name.endswith('.md'):
                    path = os.path.join(root, name)
                    all_files.append({
                        "name": name.replace(".md", ""),
                        "path": path,
                        "rel_path": os.path.relpath(path, OBSIDIAN_ROOT),
                        "mtime": os.path.getmtime(path)
                    })
    
    search_query = st.text_input("🔍 搜索...", label_visibility="collapsed")

    # 渲染逻辑
    if search_query:
        filtered = [f for f in all_files if search_query.lower() in f['name'].lower()]
        filtered.sort(key=lambda x: x['mtime'], reverse=True)
        for f in filtered:
            if st.button(f"📄 {f['name']}", key=f['path'], use_container_width=True, help=f['rel_path']):
                st.session_state.clicked_file_path = f['path']
                st.session_state.clicked_file_name = f['name']
                st.rerun()
    else:
        # === 复杂的递归树状图 (已恢复) ===
        def build_file_tree(file_list):
            tree = {}
            for f in file_list:
                parts = f['rel_path'].split(os.sep)
                current = tree
                for part in parts[:-1]:
                    current = current.setdefault(part, {})
                current[parts[-1]] = {**f, "type": "file"}
            return tree

        def render_tree(node):
            # 文件夹
            folders = {k: v for k, v in node.items() if isinstance(v, dict) and "type" not in v}
            for folder in sorted(folders.keys()):
                with st.expander(f"📁 {folder}", expanded=False):
                    render_tree(folders[folder])
            # 文件
            files = [v for k, v in node.items() if isinstance(v, dict) and v.get("type") == "file"]
            files.sort(key=lambda x: x['mtime'], reverse=True)
            for f in files:
                is_active = (f['name'] == st.session_state.get("clicked_file_name"))
                if st.button(f"📄 {f['name']}", key=f['path'], type="primary" if is_active else "secondary", use_container_width=True):
                    st.session_state.clicked_file_path = f['path']
                    st.session_state.clicked_file_name = f['name']
                    st.rerun()

        if all_files:
            tree_data = build_file_tree(all_files)
            render_tree(tree_data)
        else:
            st.caption("暂无文件")

# === 7. 主界面逻辑 ===

# 状态恢复 (防止刷新丢失)
selected_file_name = st.session_state.get("clicked_file_name")
file_path = st.session_state.get("clicked_file_path")

if selected_file_name and file_path and os.path.exists(file_path):
    # === 模式 A: 阅读/编辑模式 ===
    c_title, c_close = st.columns([6, 1])
    with c_title:
        st.title(f"📄 {selected_file_name}")
        st.caption(f"路径: {file_path}")
    with c_close:
        if st.button("❌ 关闭", use_container_width=True):
            del st.session_state.clicked_file_name
            st.rerun()

    # 编辑逻辑
    if st.session_state.get("edit_mode", False):
        with open(file_path, "r", encoding="utf-8") as f: original = f.read()
        new_content = st.text_area("编辑", value=original, height=600)
        
        c1, c2 = st.columns([1, 4])
        with c1:
            if st.button("💾 保存", type="primary", use_container_width=True):
                if new_content != original:
                    with open(file_path, "w", encoding="utf-8") as f: f.write(new_content)
                    st.toast("✅ 保存成功！")
                    # TODO: 触发后端更新向量库
                st.session_state.edit_mode = False
                st.rerun()
        with c2:
            if st.button("取消"):
                st.session_state.edit_mode = False
                st.rerun()
    else:
        if st.button("✏️ 编辑"):
            st.session_state.edit_mode = True
            st.rerun()
        st.divider()
        with open(file_path, "r", encoding="utf-8") as f:
            st.markdown(f.read())

else:
    # === 模式 B: 对话模式 (保留原版 RAG 逻辑) ===
    st.subheader("💬 知识库对话")
    
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])

    if user_input := st.chat_input("输入问题，或 '有哪些文章'..."):
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"): st.markdown(user_input)

        with st.chat_message("assistant"):
            placeholder = st.empty()
            full_response = ""
            
            # 1. 列表查询
            if check_is_list_request(user_input):
                full_response = get_article_list()
                placeholder.markdown(full_response)
            
            # 2. RAG 检索
            else:
                placeholder.markdown("🧠 思考中...")
                
                # (1) 意图判断 (追问模式)
                is_anchored = False
                search_kwargs = {"query_texts": [user_input], "n_results": 5}
                
                if st.session_state.history_doc_ids:
                    if detect_intent_with_llm(user_input, st.session_state.last_topic):
                        is_anchored = True
                        st.toast("⚓️ 触发追问模式")
                        search_kwargs["where"] = {"parent_id": {"$in": st.session_state.history_doc_ids}}
                    else:
                        st.toast("🌐 新话题，全局搜索")
                        st.session_state.history_doc_ids = []

                # (2) 执行搜索
                try:
                    results = collection.query(**search_kwargs)
                    documents = results['documents'][0]
                    metadatas = results['metadatas'][0]
                    
                    # 自动降级 (如果追问没搜到，转全局)
                    if not documents and is_anchored:
                        st.toast("🔄 追问无果，切换全局搜索...")
                        del search_kwargs["where"]
                        results = collection.query(**search_kwargs)
                        documents = results['documents'][0]
                        metadatas = results['metadatas'][0]
                        is_anchored = False

                    if not documents:
                        full_response = "🤔 知识库里没有找到相关内容。"
                    else:
                        # (3) 组装 Context
                        context_parts = []
                        current_ids = []
                        for i, doc in enumerate(documents):
                            meta = metadatas[i]
                            pid = meta.get('parent_id') or meta.get('source')
                            if pid: current_ids.append(pid)
                            context_parts.append(f"【来源{i+1}】: {doc}")
                        
                        # 更新 Session
                        if not is_anchored:
                            st.session_state.history_doc_ids = list(set(current_ids))
                            st.session_state.last_topic = user_input
                        
                        # (4) 调用 LLM
                        context_str = "\n\n".join(context_parts)
                        sys_prompt = f"你是一个助手。{'用户正在追问，' if is_anchored else ''}请基于已知信息回答。\n\n【已知信息】:\n{context_str}"
                        
                        payload = {
                            "model": LLM_MODEL,
                            "messages": [
                                {"role": "system", "content": sys_prompt},
                                {"role": "user", "content": user_input}
                            ],
                            "temperature": 0.7
                        }
                        
                        try:
                            resp = httpx.post(LLM_API_URL, json=payload, timeout=60)
                            full_response = resp.json()['choices'][0]['message']['content']
                        except Exception as e:
                            full_response = f"❌ LLM 调用失败: {e}"

                    placeholder.markdown(full_response)
                    
                    # 显示引用源
                    if documents:
                        with st.expander("📚 查看参考来源", expanded=False):
                            for i, doc in enumerate(documents):
                                meta = metadatas[i]
                                st.markdown(f"**来源 {i+1}**: `{meta.get('title','无标题')}`")
                                st.caption(f"路径: {meta.get('rel_path','未知')}")
                                st.text(doc[:100]+"...")
                                st.divider()
                                
                except Exception as e:
                    full_response = f"检索失败: {e}"
                    placeholder.error(full_response)

            st.session_state.messages.append({"role": "assistant", "content": full_response})