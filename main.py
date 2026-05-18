import os
import asyncio
import datetime
import shutil
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from agents import PlannerAgent, CodeAgent, TestAgent, FixAgent, DependencyAgent

console = Console()
HISTORY_DIR = "history"

async def main_loop():
    console.print(Panel.fit(
        "[bold magenta]Welcome to the Multi-Agent Coding Assistant[/bold magenta]\n"
        "[dim]Supports Multi-language, Planning, Auto-deps, and Async Execution[/dim]",
        border_style="magenta"
    ))
    
    planner = PlannerAgent()
    code_agent = CodeAgent()
    test_agent = TestAgent()
    fix_agent = FixAgent()
    dep_agent = DependencyAgent()
    
    while True:
        try:
            # Use standard input because rich prompt sometimes conflicts with async loops in windows
            user_prompt = console.input("\n[bold green]Enter your programming task (or 'exit' to quit):[/bold green]\n> ")
        except (EOFError, KeyboardInterrupt):
            break
            
        if user_prompt.lower() in ['exit', 'quit']:
            break
            
        if not user_prompt.strip():
            continue
            
        # 1. Plan
        plan = await planner.plan(user_prompt)
        if not plan:
            console.print("[red]Failed to generate plan.[/red]")
            continue
            
        # 2. Generate Code
        files_data = await code_agent.generate(user_prompt, plan)
        if not files_data or "files" not in files_data:
            console.print("[red]Failed to generate valid code structure. Ensure Ollama is running and outputting JSON.[/red]")
            continue
            
        files = files_data["files"]
        
        # Display Generated Code
        console.print("\n[bold magenta]--- Generated Files ---[/bold magenta]")
        for f in files:
            console.print(f"[cyan]File: {f['filename']}[/cyan]")
            ext = os.path.splitext(f["filename"])[1].lstrip(".")
            # Default to python syntax highlighting if unknown
            if not ext: ext = "python"
            syntax = Syntax(f["code"], ext, theme="monokai", line_numbers=True)
            console.print(syntax)
            
        max_retries = 3
        attempts = 0
        success = False
        output = ""
        
        # 3. Test & Fix Loop
        while attempts < max_retries and not success:
            attempts += 1
            console.print(f"\n[bold yellow]--- Test Attempt {attempts}/{max_retries} ---[/bold yellow]")
            
            success, output = await test_agent.test(files)
            
            if success:
                console.print(Panel(output, title="[green]Execution Output[/green]", border_style="green"))
                console.print("[bold green]Task completed successfully![/bold green]")
                
                import re
                
                # Create a readable folder name from the prompt
                safe_prompt = re.sub(r'[^a-zA-Z0-9]', '_', user_prompt.strip())
                safe_prompt = re.sub(r'_+', '_', safe_prompt).strip('_')
                short_prompt = safe_prompt[:40] if safe_prompt else "task"
                
                timestamp = datetime.datetime.now().strftime("%H%M%S")
                folder_name = f"{short_prompt}_{timestamp}"
                save_dir = os.path.join(HISTORY_DIR, folder_name)
                os.makedirs(save_dir, exist_ok=True)
                
                # Save prompt and plan
                with open(os.path.join(save_dir, "prompt.txt"), "w", encoding="utf-8") as f:
                    f.write(f"Prompt:\n{user_prompt}\n\nPlan:\n{plan}")
                    
                # Copy workspace files
                for item in os.listdir("workspace"):
                    s = os.path.join("workspace", item)
                    d = os.path.join(save_dir, item)
                    if os.path.isfile(s):
                        shutil.copy2(s, d)
                
                console.print(f"[dim]Saved successful execution to {save_dir}[/dim]")
                break
            else:
                console.print(Panel(output, title="[red]Error Output[/red]", border_style="red"))
                
                if attempts < max_retries:
                    # Attempt dependency fix first
                    dep_fixed = await dep_agent.analyze_and_install(output)
                    if dep_fixed:
                        console.print("[yellow]Dependency installed. Retrying execution without regenerating code...[/yellow]")
                        # We don't count this as a full logic fix attempt, 
                        # but for simplicity we let the loop continue and test again
                        attempts -= 1 
                        continue
                        
                    # If not dependency issue, ask FixAgent
                    new_files_data = await fix_agent.fix(files, output)
                    if new_files_data and "files" in new_files_data:
                        files = new_files_data["files"]
                        console.print("\n[bold magenta]--- Fixed Files ---[/bold magenta]")
                        for f in files:
                            console.print(f"[cyan]File: {f['filename']}[/cyan]")
                            ext = os.path.splitext(f["filename"])[1].lstrip(".")
                            if not ext: ext = "python"
                            syntax = Syntax(f["code"], ext, theme="monokai", line_numbers=True)
                            console.print(syntax)
                    else:
                        console.print("[red]Fix Agent failed to provide a valid JSON response.[/red]")
                        break
                else:
                    console.print("[bold red]Max retries reached. Could not fix the code.[/bold red]")

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        console.print("\n[yellow]Exiting...[/yellow]")
