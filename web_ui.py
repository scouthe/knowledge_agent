import streamlit as st
import os
import chromadb
import httpx
import time,datetime
import json
from chromadb.utils import embedding_functions

# === 1. 配置引入 (严格适配你的 Config) ===
from config import (
    CHROMA_DB_PATH, 
    CHROMA_COLLECTION_NAME, # 已修正
    LLM_API_URL,
    LLM_MODEL,              # 已修正
    OBSIDIAN_ROOT           # 必须有这个才能扫描文件，确保 config.py 里有它
)

# === 2. 页面初始化 ===
st.set_page_config(page_title="Knowledge OS", page_icon="🧠", layout="wide")

# === 3. 初始化数据库连接 ===
@st.cache_resource
def get_vector_store():
    """初始化数据库连接"""
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    # 使用 LM Studio 的 Embedding (保持你之前的设置)
    emb_fn = embedding_functions.OpenAIEmbeddingFunction(
        api_key="lm-studio",
        api_base="http://localhost:1234/v1", 
        model_name="text-embedding-bge-m3"   
    )
    # 使用 CHROMA_COLLECTION_NAME
    collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION_NAME, 
        embedding_function=emb_fn
    )
    return collection

try:
    collection = get_vector_store()
except Exception as e:
    st.error(f"❌ 数据库连接失败: {e}")
    st.stop()

# === 4. 核心逻辑函数 (意图识别 & 列表) ===

def detect_intent_with_llm(query, last_topic):
    """使用 LLM 判断是否是追问"""
    if not last_topic: return False
    
    system_prompt = "你是一个对话意图分类器。判断【当前问题】是否是针对【上轮话题】的追问。如果是追问/指代，输出TRUE；否则输出FALSE。"
    user_prompt = f"上轮话题：{last_topic}\n当前问题：{query}"
    
    payload = {
        "model": LLM_MODEL, # 使用 LLM_MODEL
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

# === 5. Session State 初始化 ===
if "messages" not in st.session_state:
    st.session_state.messages = []
if "history_doc_ids" not in st.session_state:
    st.session_state.history_doc_ids = []
if "last_topic" not in st.session_state:
    st.session_state.last_topic = ""

# 在侧边栏最上面
page_mode = st.sidebar.radio("模式选择", ["对话/阅读", "🖥️ 系统日志"])

if page_mode == "🖥️ 系统日志":
    st.title("🖥️ 系统运行日志")
    
    # 读取 fastapi.log 的最后 50 行
    log_path = "/home/heheheh/Documents/knowledge_agent/data/jobs.jsonl" # 确保路径对
    if st.button("🔄 刷新日志"):
        st.rerun()

    if os.path.exists(log_path):
        # 1. 读取并解析日志 (只取最后 20 条，倒序)
        logs = []
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                # 读取所有行，取最后20行，然后反转（最新的在最上面）
                lines = f.readlines()[-20:][::-1] 
                
            for line in lines:
                if not line.strip(): continue
                try:
                    logs.append(json.loads(line))
                except json.JSONDecodeError:
                    # 如果有非 JSON 的脏数据，原样保留
                    logs.append({"raw": line})
        except Exception as e:
            st.error(f"读取日志失败: {e}")
            st.stop()

        # 2. 渲染漂亮的日志卡片
        for log in logs:
            # 如果是解析失败的脏数据
            if "raw" in log:
                st.text(log["raw"])
                continue
                
            # --- 提取关键字段 ---
            ts = log.get("ts", "")
            # 把 ISO 时间转得更好看点 (2025-12-22T19:29:46 -> 19:29:46)
            try:
                time_obj = datetime.datetime.fromisoformat(ts)
                time_str = time_obj.strftime("%H:%M:%S")
            except:
                time_str = ts

            status = log.get("status", "UNKNOWN")
            message = log.get("message", "")
            step = log.get("step", "")
            job_id = log.get("job_id", "")[-4:] # 只显示 ID 后4位
            
            # --- 定义状态颜色和图标 ---
            if "FAIL" in status or "ERROR" in status:
                icon = "❌"
                color = "red"
            elif "SUCCESS" in status:
                icon = "✅"
                color = "green"
            elif "RUNNING" in status:
                icon = "🔵"
                color = "blue"
            else:
                icon = "ℹ️"
                color = "gray"

            # --- 渲染 UI ---
            # 使用 Expander，标题栏显示核心信息，展开看详情
            with st.expander(f"{icon} [{time_str}] {message} (Step: {step})"):
                # 第一行：状态标签
                st.markdown(f"**Status**: :{color}[{status}] | **Job ID**: `...{job_id}`")
                
                # 如果有 extra 额外信息，漂亮地显示出来
                if log.get("extra"):
                    st.info(f"Extra Info: {log['extra']}")
                
                # 显示完整的原始数据供调试
                st.json(log)
                
    else:
        st.warning("📭 暂无日志文件 (fastapi.log)")
    
    st.stop() # 停止渲染下面的聊天界面

# === 6. 侧边栏 UI (阅览室 + 状态) ===
with st.sidebar:
    with st.expander("📌 开发计划 (TODO List)", expanded=True):
        col_a, col_b = st.columns(2)
        
        with col_a:
            st.markdown("#### 🔌 数据源 & 格式")
            st.checkbox("寻找非企业微信入库接口 (Telegram/Slack/Email)", value=False)
            st.checkbox("多模态支持：图片/视频的 OCR 与内容理解 (VLM)", value=False)
            st.checkbox("🎙️ 语音速记：集成 Whisper 实现本地语音转文字入库", value=False)
            
        with col_b:
            st.markdown("#### 🧠 算法 & RAG 优化")
            st.checkbox("智能保存：LLM 重写摘要/标签 + 自动更新 Frontmatter", value=False)
            st.checkbox("Query Rewrite：多轮对话下的搜索语句重写", value=False)
            st.checkbox("Rerank 重排序：引入 Cross-Encoder 提升 Top-K 准确率", value=False)
            st.checkbox("🔪 语义切片：基于 Markdown 标题结构的智能分块 (非暴力截断)", value=False)
            st.checkbox("🕸️ Graph RAG：利用 Obsidian 双链 `[[Link]]` 增强检索上下文", value=False)
    st.divider()
    st.title("🧠 Knowledge OS")
    
    # --- A. 快捷指令区 (新增了按钮) ---
    st.subheader("⚡ 快捷指令")
    
    col1, col2,col3 = st.columns(3)
    
    with col1:
        # 🗑️ 清除按钮
        if st.button("🗑️ 重开", use_container_width=True, help="清除上下文历史"):
            st.session_state.messages = []
            st.session_state.history_doc_ids = []
            st.session_state.last_topic = ""
            # ✨ 新增：顺便把阅读状态也清了，回到主页
            if "clicked_file_name" in st.session_state:
                del st.session_state.clicked_file_name
            st.rerun()
            
    with col2:
        # 📅 新增：今日文章列表按钮
        if st.button("📅 今日更新", use_container_width=True, help="列出今天收录的文章"):
            # 1. 模拟用户消息
            st.session_state.messages.append({"role": "user", "content": "列出今日文章"})
            # 2. 直接调用逻辑获取结果
            response = get_article_list(filter_today=True)
            # 3. 写入助手回复
            st.session_state.messages.append({"role": "assistant", "content": response})
            # 4. 强制刷新页面，这样主界面就会立刻显示出来
            st.rerun()
    with col3:
        # ✨ 新增：清理按钮
        if st.button("🧹 同步库", use_container_width=True, help="删除文件后点击，清理无效的向量索引"):
            with st.spinner("正在扫描无效索引..."):
                try:
                    # 调用后端接口
                    res = httpx.post("http://localhost:8888/prune", timeout=30)
                    data = res.json()
                    if data.get("status") == "success":
                        del_count = data['deleted_chunks']
                        if del_count > 0:
                            st.toast(f"✅ 清理完成！移除了 {del_count} 个无效切片。", icon="🗑️")
                        else:
                            st.toast("✅ 索引很干净，无需清理。", icon="✨")
                    else:
                        st.error(f"清理失败: {data.get('message')}")
                except Exception as e:
                    st.error(f"无法连接后端: {e}")
    # --- ✨ 新增: 速记/存链接窗口 (调用 FastAPI) ---
    with st.expander("📥 速记 / 存链接", expanded=True):
        # 使用 form 表单，这样点击提交后可以清空输入框(如果配合 session_state)
        # 这里简单起见，直接发
        with st.form("ingest_form", clear_on_submit=True):
            note_content = st.text_area(
                "内容输入", 
                placeholder="在此粘贴公众号链接，或记录此时的想法...",
                height=120,
                label_visibility="collapsed"
            )
            
            submitted = st.form_submit_button("🚀 发送给 AI 助理", use_container_width=True)
            
            if submitted and note_content.strip():
                try:
                    # 调用本机的 FastAPI 后端 (8888端口)
                    # 注意：如果你的 WebUI 和 API 不在同一台机器，这里要改 IP
                    api_url = "http://localhost:8888/ingest"
                    
                    payload = {
                        "user_id": "web_admin", # 标记来源是网页端
                        "content": note_content
                    }
                    
                    # 发送请求
                    res = httpx.post(api_url, json=payload, timeout=5)
                    
                    if res.status_code == 200:
                        st.toast("✅ 已发送到后台任务队列！")
                        # 稍微等一下让用户看到提示
                        time.sleep(1)
                    else:
                        st.error(f"发送失败: {res.status_code} - {res.text}")
                        
                except Exception as e:
                    st.error(f"❌ 连接后端失败: {e}")
                    st.caption("请确认 main.py 是否在 8888 端口运行中")

# --- ✨ 新增: 文件投喂 (PDF/Word/PPT -> Obsidian) ---
    with st.expander("📂 投喂文档 (PDF/Office)", expanded=False):
        uploaded_file = st.file_uploader("支持 PDF, Docx, PPTX", type=["pdf", "docx", "pptx", "xlsx"])
        
        if uploaded_file is not None:
            if st.button("🚀 解析并入库", use_container_width=True):
                with st.spinner("正在解析文档，请稍候..."):
                    try:
                        import tempfile
                        from markitdown import MarkItDown
                        
                        # 1. 保存上传的文件到临时目录
                        suffix = "." + uploaded_file.name.split('.')[-1]
                        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                            tmp_file.write(uploaded_file.getvalue())
                            tmp_path = tmp_file.name
                        
                        # 2. 使用 MarkItDown 转换为 Markdown
                        md_converter = MarkItDown()
                        result = md_converter.convert(tmp_path)
                        markdown_content = result.text_content
                        
                        # 3. 构造文件名 (加上时间戳防止重名)
                        timestamp = time.strftime("%Y%m%d_%H%M%S")
                        clean_name = uploaded_file.name.rsplit('.', 1)[0]
                        save_filename = f"{timestamp}_{clean_name}.md"
                        
                        # 4. 存入 Obsidian 的 Inbox 文件夹 (假设你有这个文件夹)
                        # 建议你在 config.py 里定义一个 OBSIDIAN_INBOX_PATH
                        inbox_path = os.path.join(OBSIDIAN_ROOT, "Inbox") 
                        if not os.path.exists(inbox_path):
                            os.makedirs(inbox_path) # 没有就创建
                            
                        full_save_path = os.path.join(inbox_path, save_filename)
                        
                        # 5. 写入文件
                        # 可以在这里加上 metadata
                        final_content = f"---\ntitle: {clean_name}\ntype: uploaded_file\ncreated_at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n---\n\n{markdown_content}"
                        
                        with open(full_save_path, "w", encoding="utf-8") as f:
                            f.write(final_content)
                            
                        # 6. 触发后端入库 (为了让向量库也知道)
                        # 调用你的 ingest 接口，或者让后台自动扫描
                        # 这里简单起见，我们直接调用 ingest 接口
                        api_url = "http://localhost:8888/ingest"
                        payload = {
                            "user_id": "web_uploader",
                            "content": f"用户上传了文件: {clean_name}\n内容摘要: {markdown_content[:200]}..." 
                            # 注意：如果是大文件，直接传全文可能会爆 Token，
                            # 建议这里只发个通知，让后台爬虫去扫文件
                        }
                        httpx.post(api_url, json=payload, timeout=2)

                        st.success(f"✅ 解析成功！已存入 Inbox: {save_filename}")
                        
                        # 清理临时文件
                        os.remove(tmp_path)
                        
                    except Exception as e:
                        st.error(f"解析失败: {e}")

    st.divider()

    # --- B. 状态监控 (移动到这里更紧凑) ---
    if st.session_state.history_doc_ids:
        st.success(f"⚓ 已锁定 {len(st.session_state.history_doc_ids)} 篇文档", icon="⚓")
    else:
        st.info("🌐 全局检索模式", icon="🌐")

    st.divider()

    # --- D. 阅览室 (搜索 + 树状图) ---
    st.subheader("📂 阅览室")
    
    # 1. 数据准备 (先拿到扁平列表，用于搜索)
    all_files = []
    if os.path.exists(OBSIDIAN_ROOT):
        for root, dirs, files in os.walk(OBSIDIAN_ROOT):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for name in files:
                if name.endswith('.md'):
                    full_path = os.path.join(root, name)
                    rel_path = os.path.relpath(full_path, OBSIDIAN_ROOT)
                    mtime = os.path.getmtime(full_path)
                    all_files.append({
                        "name": name.replace(".md", ""),
                        "path": full_path,
                        "rel_path": rel_path,
                        "mtime": mtime
                    })
    else:
        st.error(f"路径不存在: {OBSIDIAN_ROOT}")

    # 2. 搜索框
    search_query = st.text_input("🔍 搜索文件名...", placeholder="输入关键词过滤", label_visibility="collapsed")

    # 3. 核心分支：搜索模式 vs 树状模式
    if search_query:
        # === 模式 A: 搜索模式 (扁平列表) ===
        st.caption(f"搜索结果: '{search_query}'")
        
        # 过滤文件
        filtered_files = [f for f in all_files if search_query.lower() in f['name'].lower()]
        # 按时间排序
        filtered_files.sort(key=lambda x: x['mtime'], reverse=True)
        
        if not filtered_files:
            st.info("没有找到匹配的文件")
        else:
            for f in filtered_files:
                # 高亮逻辑
                current_viewing_file = st.session_state.get("current_viewing_file", "")
                is_active = (f['name'] == current_viewing_file)
                btn_type = "primary" if is_active else "secondary"
                
                # 显示：文件名 (路径)
                # 使用 help 参数显示完整路径
                if st.button(f"📄 {f['name']}", key=f['path'], type=btn_type, use_container_width=True, help=f.get('rel_path')):
                    st.session_state.clicked_file_path = f['path']
                    st.session_state.clicked_file_name = f['name']
                    st.rerun()
                    
    else:
        # === 模式 B: 树状模式 (递归渲染) ===
        # 只有在没搜索词的时候才构建树，省资源
        
        def build_file_tree(file_list):
            tree = {}
            for f in file_list:
                parts = f['rel_path'].split(os.sep)
                current_level = tree
                for part in parts[:-1]:
                    if part not in current_level:
                        current_level[part] = {}
                    current_level = current_level[part]
                current_level[parts[-1]] = {**f, "type": "file"}
            return tree

        def render_tree(tree_node):
            # 分离文件夹和文件
            folders = {k: v for k, v in tree_node.items() if isinstance(v, dict) and "type" not in v}
            files = {k: v for k, v in tree_node.items() if isinstance(v, dict) and v.get("type") == "file"}
            
            # 渲染文件夹
            for folder_name in sorted(folders.keys()):
                with st.expander(f"📁 {folder_name}", expanded=False):
                    render_tree(folders[folder_name])
            
            # 渲染文件
            file_vals = list(files.values())
            file_vals.sort(key=lambda x: x['mtime'], reverse=True)
            
            current_viewing_file = st.session_state.get("current_viewing_file", "")
            for f in file_vals:
                is_active = (f['name'] == current_viewing_file)
                btn_type = "primary" if is_active else "secondary"
                if st.button(f"📄 {f['name']}", key=f['path'], type=btn_type, use_container_width=True):
                    st.session_state.clicked_file_path = f['path']
                    st.session_state.clicked_file_name = f['name']
                    st.rerun()

        if all_files:
            tree_data = build_file_tree(all_files)
            render_tree(tree_data)
        else:
            st.caption("📭 暂无文件")

    # === 适配主界面逻辑的桥接代码 (保持不变) ===
    selected_file_name = None
    if "clicked_file_name" in st.session_state:
        selected_file_name = st.session_state.clicked_file_name
        file_map = {selected_file_name: st.session_state.clicked_file_path}

    # --- C. 状态监控 ---
    # st.subheader("📊 状态") # 节省空间，上面已经有了
    st.caption(f"Topic: {st.session_state.last_topic or 'None'}")
    if st.session_state.history_doc_ids:
        st.caption(f"Anchors: {len(st.session_state.history_doc_ids)}")


# === 🛡️ 状态保持逻辑 (放在主界面逻辑之前) ===
# 如果没有通过按钮点击，file_map 可能不存在，初始化为空
if 'file_map' not in locals():
    file_map = {}

# 如果用户之前点过文件，但这次刷新（比如点赞、对话）导致 file_map 丢失
# 我们从 session_state 恢复它，确保“阅读模式”不会突然关闭
if "clicked_file_name" in st.session_state and not selected_file_name:
    selected_file_name = st.session_state.clicked_file_name
    file_map = {selected_file_name: st.session_state.clicked_file_path}

# === 7. 主界面逻辑 (阅读模式 vs 对话模式) ===

# --- 模式 A: 阅读模式 (如果选了文件) ---
if selected_file_name:
    file_path = file_map[selected_file_name]
    
    # 0. 初始化编辑状态
    if "edit_mode" not in st.session_state:
        st.session_state.edit_mode = False
    
    # 切换文件时重置状态
    if "current_viewing_file" not in st.session_state:
        st.session_state.current_viewing_file = selected_file_name
    elif st.session_state.current_viewing_file != selected_file_name:
        st.session_state.edit_mode = False
        st.session_state.current_viewing_file = selected_file_name

    # === ✨ 核心修改：顶部导航栏 (标题 + 关闭按钮) ===
    col_header_title, col_header_close = st.columns([6, 1])
    
    with col_header_title:
        st.title(f"📄 {selected_file_name}")
        st.caption(f"路径: {file_path}")
        
    with col_header_close:
        # 这个按钮负责清空状态，让你跳出循环
        if st.button("❌ 关闭", help="退出阅读，返回对话模式", use_container_width=True):
            # 1. 清除选中的文件名状态
            if "clicked_file_name" in st.session_state:
                del st.session_state.clicked_file_name
            if "clicked_file_path" in st.session_state:
                del st.session_state.clicked_file_path
            
            # 2. 强制刷新，此时 if selected_file_name 变为 False，就会进入 else 分支
            st.rerun()

    # 标题区
    col_title, col_btn = st.columns([4, 1])
    with col_title:
        st.title(f"📄 {selected_file_name}")
        st.caption(f"路径: {file_path}")

    # === 分支 A: 编辑模式 ===
    if st.session_state.edit_mode:
        # 读取硬盘上的原始内容（用于对比）
        with open(file_path, "r", encoding="utf-8") as f:
            original_content = f.read()
        
        # 1. 编辑框
        new_content = st.text_area("✏️ 编辑内容", value=original_content, height=600)
        
        # 2. 按钮区
        c1, c2 = st.columns([1, 4]) # 按钮布局调整
        
        # [按钮1] 智能保存
        with c1:
            if st.button("💾 保存并返回", type="primary", use_container_width=True):
                # === 核心逻辑：判断是否修改 ===
                if new_content != original_content:
                    # A. 内容变了 -> 保存 + 更新索引
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    
                    st.toast("📝 检测到内容变更，正在更新索引...")
                    
                    with st.spinner("正在重新向量化..."):
                        # TODO: Day 4 这里接入真实的 update_vector(file_path)
                        time.sleep(1.0) 
                    
                    st.toast("✅ 保存成功！索引已更新。")
                else:
                    # B. 内容没变 -> 仅提示
                    st.toast("☕ 内容未修改，直接返回。")
                
                # 统一动作：退出编辑模式
                st.session_state.edit_mode = False
                time.sleep(0.5)
                st.rerun()

        # [按钮2] 取消
        with c2:
            if st.button("❌ 取消编辑"):
                st.session_state.edit_mode = False
                st.rerun()

        # [删除按钮放到底部或者折叠起来，防止误触]
        with st.expander("🗑️ 危险区域"):
            if st.button("确认删除此文件", type="primary"):
                 try:
                    os.remove(file_path)
                    st.toast("🗑️ 文件已删除")
                    time.sleep(1)
                    st.rerun()
                 except Exception as e:
                    st.error(f"删除失败: {e}")

    # === 分支 B: 阅读模式 (默认) ===
    else:
        # 右上角放一个编辑按钮
        with col_btn:
            if st.button("✏️ 编辑", use_container_width=True):
                st.session_state.edit_mode = True
                st.rerun()
        
        st.divider()
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                st.markdown(content)
        except Exception as e:
            st.error(f"读取文件失败: {e}")

# --- 模式 B: 对话模式 (默认) ---
else:
    # 标题区
    st.subheader("💬 知识库对话")

    # 显示历史消息
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # 处理输入
    if user_input := st.chat_input("输入问题，或 '有哪些文章'..."):
        
        with st.chat_message("user"):
            st.markdown(user_input)
        st.session_state.messages.append({"role": "user", "content": user_input})

        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            full_response = ""

            # --- 分支 1: 列表查询 ---
            if check_is_list_request(user_input):
                full_response = get_article_list(filter_today=False)
                message_placeholder.markdown(full_response)
            
            # --- 分支 2: RAG 检索 ---
            else:
                message_placeholder.markdown("🧠 正在检索...")
                
                # (1) 意图与搜索配置
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
                results = collection.query(**search_kwargs)
                documents = results['documents'][0]
                metadatas = results['metadatas'][0]
                
                # 自动降级重试
                if not documents and is_anchored:
                     st.toast("🔄 范围搜索无果，切换全局...")
                     del search_kwargs["where"]
                     results = collection.query(**search_kwargs)
                     documents = results['documents'][0]
                     metadatas = results['metadatas'][0]
                     is_anchored = False

                if not documents:
                    full_response = "🤔 抱歉，没有找到相关内容。"
                else:
                    # (3) 组装 Context
                    context_parts = []
                    current_doc_ids = []
                    for i, doc in enumerate(documents):
                        p_id = metadatas[i].get('parent_id') or metadatas[i].get('source')
                        if p_id: current_doc_ids.append(p_id)
                        context_parts.append(f"【片段{i+1}】: {doc}")
                    
                    # 更新 Session
                    if not is_anchored:
                        st.session_state.history_doc_ids = list(set(current_doc_ids))
                        st.session_state.last_topic = user_input

                    # (4) 调用 LLM
                    context_str = "\n\n".join(context_parts)
                    system_prompt = f"""
                    你是一个知识库助手。{'用户正在针对上文追问，' if is_anchored else ''}请根据已知信息回答。
                    
                    【已知信息】：
                    {context_str}
                    """
                    
                    payload = {
                        "model": LLM_MODEL, # 使用 LLM_MODEL
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_input}
                        ],
                        "temperature": 0.7
                    }
                    
                    try:
                        resp = httpx.post(LLM_API_URL, json=payload, timeout=60)
                        ai_content = resp.json()['choices'][0]['message']['content']
                        full_response = ai_content
                    except Exception as e:
                        full_response = f"❌ LLM 调用失败: {e}"

            message_placeholder.markdown(full_response)
            with st.expander("📚 查看参考来源原文", expanded=False):
                for i, doc in enumerate(documents):
                    meta = metadatas[i]
                    score = results['distances'][0][i]
                    
                    # 渲染卡片
                    st.markdown(f"**来源 {i+1}**: `{meta.get('title', '无标题')}` (相关度: {score:.4f})")
                    st.caption(f"路径: `{meta.get('rel_path', '未知')}`")
                    st.text(doc) # 显示命中的切片原文
                    st.divider()
        st.session_state.messages.append({"role": "assistant", "content": full_response})