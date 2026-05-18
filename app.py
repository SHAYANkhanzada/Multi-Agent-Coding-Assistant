import streamlit as st
import asyncio
import os
import shutil
import datetime
import re
from agents import PlannerAgent, CodeAgent, TestAgent, FixAgent, DependencyAgent, ResearchAgent, ReviewAgent, DocsAgent

# Windows specific event loop policy for subprocesses
if os.name == 'nt':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

st.set_page_config(page_title="Multi-Agent Coding Assistant", page_icon="🤖", layout="wide")

# 🎓 Course & Member Information Header
with st.container(border=True):
    st.markdown("### 🎓 **Agentic AI Project**")
    st.markdown(
        "**Developer:** Shayan Akram (ID: 14958)  \n"
        "**Class ID:** 120055"
    )

st.title("🤖 Multi-Agent Coding Assistant")
st.markdown("Supports **Multi-language**, **Planning**, **Auto-deps**, **Research**, **Security Review**, and **Docs Generation**.")

HISTORY_DIR = "history"
os.makedirs(HISTORY_DIR, exist_ok=True)

# ----------------- SIDEBAR -----------------
with st.sidebar:
    st.header("⚙️ Settings")
    auto_install = st.toggle("Auto-Install Dependencies", value=True, help="If enabled, Dependency Agent will automatically pip install missing packages.")
    enable_research = st.toggle("Enable Web Research", value=False, help="Search the web for up-to-date documentation and APIs before planning.")
    enable_review = st.toggle("Enable Security & Code Review", value=False, help="Have a Security Agent review and refactor code before running.")
    enable_docs = st.toggle("Generate Documentation (README.md)", value=False, help="Create a comprehensive README markdown file for your project.")
    
    st.header("📂 Past Projects")
    history_folders = sorted(os.listdir(HISTORY_DIR), reverse=True) if os.path.exists(HISTORY_DIR) else []
    
    if not history_folders:
        st.info("No past projects found.")
    else:
        selected_project = st.selectbox("View a past project:", ["None"] + history_folders)
        if selected_project != "None":
            st.subheader(f"Project: {selected_project}")
            proj_dir = os.path.join(HISTORY_DIR, selected_project)
            for item in os.listdir(proj_dir):
                filepath = os.path.join(proj_dir, item)
                if os.path.isfile(filepath) and not item.endswith(".zip"):
                    with st.expander(f"📄 {item}"):
                        with open(filepath, "r", encoding="utf-8") as f:
                            st.code(f.read(), language="markdown" if item.endswith(".md") else "python")
            
            # Zip Download for past project
            zip_path = os.path.join(proj_dir, f"{selected_project}.zip")
            if not os.path.exists(zip_path):
                shutil.make_archive(os.path.join(proj_dir, selected_project), 'zip', proj_dir)
            with open(zip_path, "rb") as f:
                st.download_button("📥 Download ZIP", data=f, file_name=f"{selected_project}.zip", mime="application/zip", key=f"dl_{selected_project}")

# ----------------- MAIN UI -----------------

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if user_input := st.chat_input("Enter your programming task (e.g. 'Write a python script to fetch a random joke')..."):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        planner = PlannerAgent()
        code_agent = CodeAgent()
        test_agent = TestAgent()
        fix_agent = FixAgent()
        dep_agent = DependencyAgent()
        research_agent = ResearchAgent()
        review_agent = ReviewAgent()
        docs_agent = DocsAgent()
        
        # 0. Research Phase
        if enable_research:
            with st.status("🌐 Researching...", expanded=True) as status:
                def update_status(msg):
                    status.write(msg)
                
                research_context = asyncio.run(research_agent.research(user_input, status_callback=update_status))
                
                if research_context:
                    st.info("Found relevant context online!")
                    with st.expander("Web Context"):
                        st.markdown(research_context)
                    prompt = f"{user_input}\n\n{research_context}"
                else:
                    prompt = user_input
                status.update(label="Research Complete", state="complete")
        else:
            prompt = user_input
            def update_status(msg):
                pass
        
        # 1. Plan Phase
        st.subheader("📝 Architecture Plan")
        plan_placeholder = st.empty()
        
        async def run_planner():
            full_plan = ""
            async for chunk in planner.plan(prompt):
                full_plan += chunk
                plan_placeholder.markdown(full_plan + "▌")
            plan_placeholder.markdown(full_plan)
            return full_plan

        plan = asyncio.run(run_planner())
        
        # 2. Code Generation & Review
        st.subheader("💻 Code Generation & Review")
        with st.status("Generating Code...", expanded=True) as status:
            files_data = asyncio.run(code_agent.generate(prompt, plan, status_callback=update_status))
            
            if not files_data or "files" not in files_data:
                st.error("Failed to generate valid code structure. Ensure Ollama is running and outputting JSON.")
                status.update(label="Failed", state="error")
                st.stop()
                
            files = files_data["files"]
            
            # Review phase
            if enable_review:
                update_status("🛡️ Reviewing code for security and best practices...")
                reviewed_data = asyncio.run(review_agent.review(files, status_callback=update_status))
                if reviewed_data and "files" in reviewed_data:
                    files = reviewed_data["files"]
            
            for f in files:
                with st.expander(f"📄 {f['filename']}", expanded=True):
                    ext = os.path.splitext(f['filename'])[1].lstrip('.') or 'python'
                    st.code(f["code"], language=ext)
            status.update(label="Code Generation & Review Complete!", state="complete")
        
        # 3. Test & Fix Loop
        st.subheader("🧪 Testing & Execution")
        max_retries = 3
        attempts = 0
        success = False
        output = ""
        
        while attempts < max_retries and not success:
            attempts += 1
            with st.status(f"Running Test Attempt {attempts}/{max_retries}...", expanded=True) as status:
                def test_status(msg):
                    status.write(msg)
                
                success, output = asyncio.run(test_agent.test(files, status_callback=test_status))
                
                if success:
                    st.success("✅ **Execution Successful!**")
                    st.code(output, language="bash")
                    status.update(label="Execution Successful!", state="complete")
                    
                    # 4. Generate Documentation
                    if enable_docs:
                        with st.spinner("📝 Generating README.md..."):
                            files = asyncio.run(docs_agent.document(files, status_callback=test_status))
                            readme = next((f['code'] for f in files if f['filename'] == 'README.md'), "")
                            if readme:
                                with st.expander("📄 README.md", expanded=True):
                                    st.markdown(readme)
                    
                    # Save to History
                    safe_prompt = re.sub(r'[^a-zA-Z0-9]', '_', user_input.strip())
                    safe_prompt = re.sub(r'_+', '_', safe_prompt).strip('_')
                    short_prompt = safe_prompt[:40] if safe_prompt else "task"
                    timestamp = datetime.datetime.now().strftime("%H%M%S")
                    folder_name = f"{short_prompt}_{timestamp}"
                    save_dir = os.path.join(HISTORY_DIR, folder_name)
                    os.makedirs(save_dir, exist_ok=True)
                    
                    with open(os.path.join(save_dir, "prompt.txt"), "w", encoding="utf-8") as f:
                        f.write(f"Prompt:\n{prompt}\n\nPlan:\n{plan}")
                        
                    for f_dict in files:
                        with open(os.path.join(save_dir, f_dict["filename"]), "w", encoding="utf-8") as file_out:
                            file_out.write(f_dict["code"])
                    
                    # Generate ZIP
                    zip_base = os.path.join(save_dir, folder_name)
                    shutil.make_archive(zip_base, 'zip', save_dir)
                    zip_path = zip_base + ".zip"
                    
                    st.caption(f"💾 Saved successful execution to `{save_dir}`")
                    
                    with open(zip_path, "rb") as f:
                        st.download_button("📥 Download Final Project (ZIP)", data=f, file_name=f"{folder_name}.zip", mime="application/zip")
                    break
                else:
                    st.error("❌ **Execution Failed:**")
                    st.code(output, language="bash")
                    status.update(label="Execution Failed", state="error")
                    
                    if attempts < max_retries:
                        if auto_install:
                            # Attempt dependency fix first
                            dep_fixed = asyncio.run(dep_agent.analyze_and_install(output, status_callback=test_status))
                            if dep_fixed:
                                st.warning("📦 Dependency installed. Retrying execution...")
                                attempts -= 1 
                                continue
                        else:
                            if "ModuleNotFoundError" in output or "ImportError" in output:
                                st.error("🚨 Missing Dependency Detected! Auto-Install is turned OFF in sidebar. Please install manually or turn on the toggle and retry.")
                                break
                            
                        # If not dependency issue or if auto_install failed, ask FixAgent
                        with st.spinner("🔧 Fixing code..."):
                            new_files_data = asyncio.run(fix_agent.fix(files, output, status_callback=test_status))
                            if new_files_data and "files" in new_files_data:
                                files = new_files_data["files"]
                                st.info("✨ Code Fixed! Regenerated files:")
                                for f in files:
                                    with st.expander(f"📄 Fixed File: {f['filename']}", expanded=True):
                                        ext = os.path.splitext(f['filename'])[1].lstrip('.') or 'python'
                                        st.code(f["code"], language=ext)
                            else:
                                st.error("Fix Agent failed to provide a valid JSON response.")
                                break
                    else:
                        st.error("🚨 Max retries reached. Could not fix the code.")

        # Save to chat history
        st.session_state.messages.append({"role": "assistant", "content": "Task processing finished. Review the output above."})
