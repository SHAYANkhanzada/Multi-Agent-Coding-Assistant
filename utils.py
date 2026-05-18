import os
import json
import re
import aiohttp
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()
OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/generate")
MODEL_NAME = os.getenv("MODEL_NAME", "mistral")
console = Console()

async def query_ollama(prompt: str, system_prompt: str = "", json_format: bool = False) -> str:
    """Async helper for non-streaming Ollama API calls."""
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "system": system_prompt,
        "stream": False
    }
    if json_format:
        payload["format"] = "json"
        
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(OLLAMA_API_URL, json=payload) as response:
                response.raise_for_status()
                data = await response.json()
                return data.get("response", "")
        except Exception as e:
            console.print(f"[bold red]Error communicating with Ollama: {e}[/bold red]")
            return ""

async def query_ollama_stream(prompt: str, system_prompt: str = ""):
    """Async generator for streaming Ollama API calls."""
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "system": system_prompt,
        "stream": True
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(OLLAMA_API_URL, json=payload) as response:
                response.raise_for_status()
                async for line in response.content:
                    if line:
                        data = json.loads(line)
                        chunk = data.get("response", "")
                        yield chunk
        except Exception as e:
            yield f"\nError communicating with Ollama: {e}"

def extract_json(text: str) -> dict:
    """Extracts JSON from text, even if wrapped in markdown blocks."""
    # Find anything that looks like JSON
    match = re.search(r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```', text, re.DOTALL | re.IGNORECASE)
    if match:
        json_str = match.group(1).strip()
    else:
        json_str = text.strip()
    
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        console.print(f"[bold red]Failed to parse JSON: {e}[/bold red]")
        return None

def extract_code(text: str) -> str:
    """Extracts code from a markdown block."""
    match = re.search(r'```(?:\w+)?\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text.strip()
