import os
import subprocess
import asyncio
from duckduckgo_search import DDGS
from utils import query_ollama, query_ollama_stream, extract_json, extract_code

WORKSPACE_DIR = "workspace"

def default_log(msg):
    print(msg)

class PlannerAgent:
    async def plan(self, user_prompt: str):
        system_prompt = (
            "You are a Senior Software Architect. Break down the user's request into a concrete, step-by-step implementation plan. "
            "Outline the required files, the architecture, and the logic. Do NOT write the actual code. "
            "Keep the plan concise but comprehensive."
        )
        async for chunk in query_ollama_stream(user_prompt, system_prompt):
            yield chunk

class CodeAgent:
    async def generate(self, user_prompt: str, plan: str, status_callback=default_log) -> dict:
        status_callback("💻 Generating code based on the plan...")
        system_prompt = (
            "You are an expert Developer. You will be given a user prompt and an architectural plan. "
            "Your task is to write the complete, executable code based on the plan. "
            "You MUST output the code in a JSON format where the root is an object with a 'files' array. "
            "Each object in the array should have 'filename' (string) and 'code' (string). "
            "Example: {\"files\": [{\"filename\": \"main.py\", \"code\": \"print('hello')\"}]} "
            "Do NOT output anything else except the JSON block. "
            "IMPORTANT: Do NOT use interactive input() or prompt the user. Use hardcoded test values to demonstrate functionality."
        )
        prompt = f"User Request: {user_prompt}\n\nArchitecture Plan:\n{plan}"
        
        response = await query_ollama(prompt, system_prompt, json_format=True)
        
        if response:
            return extract_json(response)
        return None

class TestAgent:
    async def test(self, files: list, status_callback=default_log) -> tuple:
        status_callback("🧪 Running tests...")
        if not os.path.exists(WORKSPACE_DIR):
            os.makedirs(WORKSPACE_DIR)

        # Write all files to workspace
        entry_file = None
        for f in files:
            filename = f.get("filename")
            code = f.get("code")
            filepath = os.path.join(WORKSPACE_DIR, filename)
            with open(filepath, "w", encoding="utf-8") as file_out:
                file_out.write(code)
            
            # Simple heuristic: first py/js file or main.* is entry
            if entry_file is None or filename.startswith("main"):
                entry_file = filepath

        if not entry_file:
            return False, "No executable files found."

        ext = os.path.splitext(entry_file)[1]
        
        if ext == ".py":
            cmd = ["python", entry_file]
        elif ext == ".js":
            cmd = ["node", entry_file]
        elif ext == ".cpp":
            build_cmd = ["g++", entry_file, "-o", os.path.join(WORKSPACE_DIR, "out")]
            status_callback(f"Compiling C++ code: {' '.join(build_cmd)}")
            try:
                build_res = subprocess.run(build_cmd, capture_output=True, text=True)
                if build_res.returncode != 0:
                    return False, f"Compilation Error:\n{build_res.stderr}"
            except FileNotFoundError:
                return False, "Error: C++ compiler 'g++' not found. Please ask the agent to write in Python instead, or install MinGW."
            cmd = [os.path.join(WORKSPACE_DIR, "out")]
            if os.name == 'nt':
                cmd = [os.path.join(WORKSPACE_DIR, "out.exe")]
        else:
            return False, f"Unsupported file extension: {ext}"

        status_callback(f"Executing: {' '.join(cmd)}")
        
        try:
            try:
                # Use asyncio.create_subprocess_exec for async execution
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
            except FileNotFoundError:
                return False, f"Error: Execution command '{cmd[0]}' not found."
            
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
                
                if proc.returncode == 0:
                    status_callback("✅ Execution successful!")
                    return True, stdout.decode()
                else:
                    status_callback("❌ Execution failed.")
                    error_msg = stderr.decode() if stderr else stdout.decode()
                    return False, error_msg
            except asyncio.TimeoutError:
                proc.kill()
                return False, "Error: Execution timed out (potential infinite loop)."
                
        except Exception as e:
            return False, str(e)

class DependencyAgent:
    async def analyze_and_install(self, error_message: str, status_callback=default_log) -> bool:
        """Parses ModuleNotFoundError and installs dependencies."""
        if "ModuleNotFoundError" in error_message or "ImportError" in error_message:
            status_callback("📦 Detected missing Python dependency. Attempting to install...")
            
            prompt = (
                f"Extract ONLY the missing pip package name from this error message:\n{error_message}\n"
                f"Output strictly the package name, nothing else."
            )
            package_name = await query_ollama(prompt, system_prompt="You are an expert package manager.")
            package_name = package_name.strip() if package_name else ""
            
            if package_name:
                status_callback(f"Running pip install {package_name}...")
                proc = await asyncio.create_subprocess_exec(
                    "pip", "install", package_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode == 0:
                    status_callback(f"✅ Successfully installed {package_name}")
                    return True
                else:
                    status_callback(f"❌ Failed to install {package_name}")
        return False

class FixAgent:
    async def fix(self, files: list, error_message: str, status_callback=default_log) -> dict:
        status_callback("🔧 Analyzing error and fixing code...")
        system_prompt = (
            "You are an expert Debugger. You will be provided with the current files and an error message. "
            "Your task is to fix the code to resolve the error. "
            "You MUST output the code in a JSON format with a 'files' array, just like before. "
            "Example: {\"files\": [{\"filename\": \"main.py\", \"code\": \"print('hello fixed')\"}]} "
            "IMPORTANT: Do NOT use interactive input() or prompt the user. Use hardcoded test values to demonstrate functionality."
        )
        
        files_context = "\n".join([f"--- {f['filename']} ---\n{f['code']}" for f in files])
        prompt = f"Current Files:\n{files_context}\n\nError Message:\n{error_message}\n\nPlease provide the complete fixed files in JSON format."
        
        response = await query_ollama(prompt, system_prompt, json_format=True)
            
        if response:
            return extract_json(response)
        return None

class ResearchAgent:
    async def research(self, user_prompt: str, status_callback=default_log) -> str:
        status_callback("🌐 Researching the web for context...")
        extract_prompt = f"Extract a single precise search query from this prompt to look up documentation or recent info: {user_prompt}\nReturn ONLY the query string, nothing else."
        query = await query_ollama(extract_prompt)
        query = query.strip().strip('"\'')
        
        if not query:
            return ""
            
        status_callback(f"🌐 Searching DuckDuckGo for: {query}")
        try:
            results = DDGS().text(query, max_results=3)
            if not results:
                return ""
            
            context = "Web Search Results:\n"
            for r in results:
                context += f"- {r['title']}: {r['body']}\n"
            return context
        except Exception as e:
            status_callback(f"⚠️ Search failed: {e}")
            return ""

class ReviewAgent:
    async def review(self, files: list, status_callback=default_log) -> dict:
        status_callback("🛡️ Reviewing code for security and best practices...")
        system_prompt = (
            "You are an expert Code Reviewer and Security Analyst. Review the provided code files. "
            "Fix any security vulnerabilities, bad practices, or missing edge cases. "
            "You MUST output the revised code in a JSON format where the root is an object with a 'files' array. "
            "Each object should have 'filename' and 'code'. Example: {\"files\": [{\"filename\": \"main.py\", \"code\": \"print('hello')\"}]} "
            "IMPORTANT: Do NOT use interactive input() or prompt the user. Use hardcoded test values to demonstrate functionality. "
            "If no changes are needed, just return the exact same files in JSON."
        )
        files_context = "\n".join([f"--- {f['filename']} ---\n{f['code']}" for f in files])
        prompt = f"Code Files:\n{files_context}\n\nPlease provide the reviewed and refactored files in JSON format."
        
        response = await query_ollama(prompt, system_prompt, json_format=True)
        if response:
            return extract_json(response)
        return {"files": files} # fallback to original

class DocsAgent:
    async def document(self, files: list, status_callback=default_log) -> list:
        status_callback("📝 Generating Documentation (README.md)...")
        system_prompt = (
            "You are an expert Technical Writer. Write a comprehensive README.md file for the provided code files. "
            "Explain what the code does, how to run it, and any dependencies. "
            "Return ONLY the markdown content for README.md, do not wrap it in a JSON array."
        )
        files_context = "\n".join([f"--- {f['filename']} ---\n{f['code']}" for f in files])
        prompt = f"Code Files:\n{files_context}\n\nPlease write the README.md."
        
        response = await query_ollama(prompt, system_prompt)
        
        if response:
            readme_code = extract_code(response)
            files.append({"filename": "README.md", "code": readme_code})
        return files
