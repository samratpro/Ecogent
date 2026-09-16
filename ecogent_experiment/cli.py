"""
Ecogent Experiment CLI.

Click-based command-line interface for running the experiment.
"""

import json
import os
import platform
import sys
from pathlib import Path

import click
import psutil

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt
from rich.markdown import Markdown
from rich.text import Text
from rich.align import Align

from ecogent_experiment import __version__

console = Console()

def get_project_root() -> str:
    """Get the project root directory."""
    current = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(current)
    if os.path.exists(os.path.join(parent, "config", "config.json")):
        return parent
    return parent

def get_config() -> dict:
    """Load project configuration."""
    root = get_project_root()
    config_path = os.path.join(root, "config", "config.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            return json.load(f)
    return {}

@click.group()
@click.version_option(version=__version__, prog_name="ecogent")
def cli():
    """Ecogent - Local-First Multi-Agent Research Prototype."""
    pass


# ============================================================
# system-info
# ============================================================

@cli.command("system-info")
def system_info():
    """Display system and environment information."""
    root = get_project_root()
    config = get_config()

    console.print()
    title = Panel("[bold cyan]ECOGENT SYSTEM INFORMATION[/bold cyan]", border_style="cyan", expand=False)
    console.print(Align.center(title))
    console.print()

    table = Table(show_header=True, header_style="bold magenta", expand=True)
    table.add_column("Category", style="dim", width=20)
    table.add_column("Property")
    table.add_column("Value", style="green")

    # System
    ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)
    gpu = "None detected"
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            gpu = result.stdout.strip().split("\n")[0]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    table.add_row("System", "OS", f"{platform.system()} {platform.release()}")
    table.add_row("", "CPU", f"{platform.processor() or platform.machine()}")
    table.add_row("", "CPU Cores", str(os.cpu_count()))
    table.add_row("", "RAM", f"{ram_gb} GB")
    table.add_row("", "GPU", gpu)
    table.add_section()

    # Python
    venv = os.path.exists(os.path.join(root, ".venv"))
    table.add_row("Python", "Version", f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    table.add_row("", "Virtual Env", "Active" if venv else "Not found")
    table.add_section()

    # Model
    model_meta_path = os.path.join(root, "config", "model.json")
    if os.path.exists(model_meta_path):
        with open(model_meta_path) as f:
            model_meta = json.load(f)
        size_mb = model_meta.get("file_size_bytes", 0) / (1024 * 1024)
        table.add_row("Local LLM", "Model", model_meta.get('name', 'Unknown'))
        table.add_row("", "Format", model_meta.get('format', 'Unknown'))
        table.add_row("", "Quantization", model_meta.get('quantization', 'Unknown'))
        table.add_row("", "Parameters", str(model_meta.get('parameters', 'Unknown')))
        table.add_row("", "Size", f"{size_mb:.1f} MB")
    else:
        table.add_row("Local LLM", "Status", "[red]Not installed (run bootstrap.py)[/red]")
    table.add_section()

    # Runtime
    runtime_cfg = config.get("llm_runtime", {})
    runtime_path = os.path.join(root, runtime_cfg.get("path", ""))
    if os.name == "nt" and not runtime_path.endswith(".exe"):
        runtime_path += ".exe"
    table.add_row("Inference", "Type", runtime_cfg.get('type', 'Unknown'))
    table.add_row("", "Available", "[green]Yes[/green]" if os.path.exists(runtime_path) else "[red]No[/red]")
    table.add_section()

    # Chroma
    try:
        import chromadb
        chroma_dir = os.path.join(root, "data", "chroma")
        if os.path.exists(chroma_dir):
            client = chromadb.PersistentClient(path=chroma_dir)
            collections = client.list_collections()
            table.add_row("Memory (Chroma)", "Version", f"v{chromadb.__version__}")
            table.add_row("", "Collections", str(len(collections)))
            for c in collections:
                table.add_row("", f" - {c.name}", f"{c.count()} items")
        else:
            table.add_row("Memory", "Status", "[yellow]Not initialized[/yellow]")
    except ImportError:
        table.add_row("Memory", "Status", "[red]ChromaDB not installed[/red]")
    table.add_section()



    console.print(table)
    console.print()


# ============================================================
# infer
# ============================================================

@cli.command("infer")
@click.option("--model", default=None, help="Path to GGUF model file.")
@click.option("--prompt", required=True, help="Prompt text for inference.")
@click.option("--max-tokens", default=128, help="Maximum tokens to generate.")
@click.option("--raw", is_flag=True, help="Show raw output without JSON parsing.")
def infer(model, prompt, max_tokens, raw):
    """Run a single Tiny LLM inference."""
    from ecogent_experiment.inference import InferenceEngine, create_engine_from_config
    from ecogent_experiment.parser import extract_json

    root = get_project_root()
    config_path = os.path.join(root, "config", "config.json")

    if model:
        config = get_config()
        runtime_cfg = config.get("llm_runtime", {})
        runtime_path = os.path.join(root, runtime_cfg.get("path", "runtime/llama-cli"))
        if os.name == "nt" and not runtime_path.endswith(".exe"):
            runtime_path += ".exe"
        engine = InferenceEngine(
            runtime_path=runtime_path,
            model_path=model,
        )
    else:
        engine = create_engine_from_config(config_path)

    if not engine.verify():
        console.print("[bold red]Error:[/bold red] Runtime or model not found. Run bootstrap.py first.")
        sys.exit(1)

    console.print(f"[dim]Model: {os.path.basename(engine.model_path)}[/dim]")
    console.print(f"[dim]Prompt: {prompt}[/dim]\n")

    # Use TinyLLM for structured inference
    from ecogent_experiment.tiny_llm import TinyLLM
    llm = TinyLLM(engine)
    
    with console.status("[bold green]Running inference..."):
        decision = llm.classify_task(prompt)

    if raw:
        console.print(Panel(decision.raw_output, title="Raw Output", border_style="yellow"))
    else:
        console.print(Panel(json.dumps(decision.to_dict(), indent=2), title="Decision Output", border_style="cyan"))

    metrics = f"[bold]Latency:[/bold] {decision.latency_ms:.1f} ms | [bold]JSON Valid:[/bold] {decision.json_valid}"
    console.print(metrics)


# ============================================================
# inspect-tool
# ============================================================

@cli.command("inspect-tool")
@click.argument("tool_name")
def inspect_tool(tool_name):
    """Inspect a registered tool."""
    root = get_project_root()

    try:
        import chromadb
        chroma_dir = os.path.join(root, "data", "chroma")
        client = chromadb.PersistentClient(path=chroma_dir)

        for collection_name in ["builtin_tools", "generated_tools"]:
            try:
                collection = client.get_collection(collection_name)
                result = collection.get(ids=[tool_name])
                if result and result["ids"]:
                    panel_content = f"[bold green]Description:[/bold green]\n{result['documents'][0]}\n\n"
                    if result["metadatas"]:
                        panel_content += "[bold cyan]Metadata:[/bold cyan]\n"
                        for key, value in result["metadatas"][0].items():
                            panel_content += f"  - [yellow]{key}[/yellow]: {value}\n"
                            
                    console.print(Panel(panel_content, title=f"Tool: {tool_name} (in {collection_name})", border_style="cyan"))
                    return
            except Exception:
                continue

        console.print(f"[bold red]Tool '{tool_name}' not found in any collection.[/bold red]")

    except ImportError:
        console.print("[bold red]ChromaDB not installed. Run bootstrap.py first.[/bold red]")


# ============================================================
# inspect-workflow
# ============================================================

@cli.command("inspect-workflow")
@click.option("--project-id", default=None, help="Specific project ID to inspect.")
def inspect_workflow(project_id):
    """Inspect active workflow state."""
    root = get_project_root()
    workflows_dir = os.path.join(root, "workflows")

    if not os.path.exists(workflows_dir):
        console.print("[yellow]No workflows directory found.[/yellow]")
        return

    workflow_files = [f for f in os.listdir(workflows_dir) if f.endswith(".json")]

    if not workflow_files:
        console.print("[yellow]No active workflows.[/yellow]")
        return

    for wf_file in workflow_files:
        wf_path = os.path.join(workflows_dir, wf_file)
        with open(wf_path) as f:
            workflow = json.load(f)

        if project_id and workflow.get("project_id") != project_id:
            continue
            
        tree = workflow.get("project_tree", [])
        
        table = Table(title=f"Workflow: {wf_file} | Project: {workflow.get('project_name', 'Unknown')}", expand=True)
        table.add_column("Status", width=12)
        table.add_column("Node ID", style="cyan")
        table.add_column("Task Title")
        
        for node in tree:
            status = node.get("status", "pending")
            status_style = {
                "pending": "[dim]pending[/dim]",
                "in_progress": "[yellow]in_progress[/yellow]",
                "completed": "[green]completed[/green]",
                "failed": "[red]failed[/red]",
            }.get(status, f"[{status}]")
            
            table.add_row(
                status_style,
                node.get('node_id', '?'),
                node.get('task_title', 'Untitled')
            )
            
        console.print(table)


# ============================================================
# benchmark (stub for Phase 8)
# ============================================================

@cli.command("token-count")
def token_count():
    """Run token counter to evaluate token usage."""
    from ecogent_experiment.token_counter import run_token_counter
    import os
    tasks_file = os.path.join(os.path.dirname(__file__), "..", "benchmark", "tasks.json")
    run_token_counter(tasks_file)


# ============================================================
# config
# ============================================================

@cli.group("config")
def config_cli():
    """Manage Ecogent configuration."""
    pass

@config_cli.command("list")
def config_list():
    """List configured cloud providers."""
    config = get_config()
    providers = config.get("cloud_providers", {})
    default = providers.get("default", "mock")
    
    table = Table(title="Cloud Providers Configured", border_style="cyan")
    table.add_column("Default", justify="center")
    table.add_column("Provider Name", style="bold")
    table.add_column("Model")
    table.add_column("API Key Set")
    
    for key, val in providers.items():
        if key == "default":
            continue
        is_default = "[green]*[/green]" if key == default else ""
        model = val.get("model", "N/A")
        has_key = "[green]Yes[/green]" if val.get("api_key") else "[dim]No[/dim]"
        table.add_row(is_default, key, model, has_key)
        
    console.print(table)

@config_cli.command("use")
@click.argument("provider_name")
def config_use(provider_name):
    """Set the default cloud provider."""
    root = get_project_root()
    config_path = os.path.join(root, "config", "config.json")
    
    with open(config_path, "r") as f:
        config = json.load(f)
        
    providers = config.get("cloud_providers", {})
    if provider_name not in providers and provider_name != "mock":
        console.print(f"[red]Provider {provider_name} not found in config.[/red]")
        return
        
    config["cloud_providers"]["default"] = provider_name
    
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
        
    console.print(f"[bold green]Default provider successfully set to:[/bold green] [cyan]{provider_name}[/cyan]")

@config_cli.command("set-provider")
@click.argument("provider_name")
@click.option("--api-key", help="API Key for the provider")
@click.option("--model", help="Model name to use")
@click.option("--url", help="Base URL (primarily for ollama)")
def config_set_provider(provider_name, api_key, model, url):
    """Configure a specific cloud provider."""
    root = get_project_root()
    config_path = os.path.join(root, "config", "config.json")
    
    with open(config_path, "r") as f:
        config = json.load(f)
        
    if "cloud_providers" not in config:
        config["cloud_providers"] = {}
        
    if provider_name not in config["cloud_providers"]:
        config["cloud_providers"][provider_name] = {}
        
    provider = config["cloud_providers"][provider_name]
    
    if api_key is not None:
        provider["api_key"] = api_key
    if model is not None:
        provider["model"] = model
    if url is not None:
        provider["base_url"] = url
        
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
        
    console.print(f"[bold green]Updated configuration for {provider_name}.[/bold green]")


# ============================================================
# chat
# ============================================================

@cli.command("chat")
def chat():
    """Interactive Ecogent terminal."""
    from ecogent_experiment.inference import create_engine_from_config
    from ecogent_experiment.tiny_llm import TinyLLM
    from ecogent_experiment.supervisor import Supervisor
    from ecogent_experiment.router import Router
    from ecogent_experiment.providers.cloud import create_cloud_provider
    
    root = get_project_root()
    config_path = os.path.join(root, "config", "config.json")
    config = get_config()
    
    console.print()
    title = Panel("[bold blue]ECOGENT AGENT TERMINAL[/bold blue]\n[dim]Local-First Intelligent Routing System[/dim]", border_style="blue", expand=False)
    console.print(Align.center(title))
    console.print()
    
    while True:
        menu_text = (
            "[bold]1.[/bold] Start new session\n"
            "[bold]2.[/bold] Load existing session\n"
            "[bold]3.[/bold] Delete existing session\n"
            "[bold]4.[/bold] Configure Cloud API Fallback\n"
            "[bold]5.[/bold] Exit"
        )
        console.print(Panel(menu_text, title="Main Menu", border_style="cyan", expand=False))
        choice = Prompt.ask("Select an option", choices=["1", "2", "3", "4", "5"], default="1")
        
        if choice == "5":
            console.print("[dim]Exiting terminal. Goodbye![/dim]")
            break
            
        if choice == "4":
            console.print()
            guide_text = (
                "To configure your Cloud API Fallback providers (OpenAI, OpenRouter, Ollama):\n\n"
                "1. Open [bold cyan]config/config.json[/bold cyan] in your editor.\n"
                "2. Locate the [bold green]\"cloud_providers\"[/bold green] section.\n"
                "3. Enter your API keys and preferred models directly in the JSON structure:\n\n"
                "   [dim]{\n"
                "     \"openrouter\": {\n"
                "       \"api_key\": \"sk-or-v1-...\",\n"
                "       \"model\": \"meta-llama/llama-3-70b-instruct\"\n"
                "     }\n"
                "   }[/dim]\n\n"
                "4. Change the [bold yellow]\"default\"[/bold yellow] field to your preferred provider (e.g., \"openrouter\").\n\n"
                "[bold red]⚠️ Important:[/bold red] Ensure the model you configure has strong tool-calling and JSON-formatting capabilities (e.g., GPT-4o, Claude 3.5 Sonnet, Llama-3-70B-Instruct).\n\n"
                "Alternatively, you can use the CLI command: [cyan]ecogent config set-provider[/cyan]\n"
                "See the [bold]README.md[/bold] for more details."
            )
            console.print(Panel(guide_text, title="Cloud API Configuration Guide", border_style="yellow", expand=False))
            console.print()
            continue
            
        from ecogent_experiment.db import ProjectDB
        db = ProjectDB(root)
        
        if choice == "3":
            projects = db.list_projects()
            if not projects:
                console.print("[yellow]No existing projects found to delete.[/yellow]")
                continue
                
            table = Table(show_header=True, header_style="bold magenta", box=None)
            table.add_column("No.")
            table.add_column("Project ID")
            table.add_column("Name")
            
            proj_list = list(projects.items())
            for i, (pid, pdata) in enumerate(proj_list, 1):
                table.add_row(f"[bold cyan]{i}.[/bold cyan]", pid, pdata["name"])
            console.print(Panel(table, title="Delete Project", border_style="red", expand=False))
            
            sel = Prompt.ask(f"Select a project to delete [1-{len(proj_list)}]")
            try:
                idx = int(sel) - 1
                if 0 <= idx < len(proj_list):
                    del_pid = proj_list[idx][0]
                    # Get chroma registry to delete tools
                    from ecogent_experiment.tool_registry import ToolRegistry
                    chroma_dir = os.path.join(root, "data", "chroma_db")
                    try:
                        tr = ToolRegistry(chroma_dir)
                        deleted_tools = tr.deregister_project_tools(del_pid)
                    except Exception as e:
                        deleted_tools = 0
                        
                    if db.delete_project(del_pid):
                        console.print(f"[bold green]Successfully deleted project:[/bold green] {del_pid}. Also deleted {deleted_tools} generated tools from ChromaDB.")
                    else:
                        console.print(f"[bold red]Failed to delete project:[/bold red] {del_pid}")
                else:
                    console.print("[yellow]Invalid choice. Returning to main menu.[/yellow]")
            except ValueError:
                console.print("[yellow]Invalid choice. Returning to main menu.[/yellow]")
            continue
        
        project_id = None
        
        if choice == "2":
            projects = db.list_projects()
            if not projects:
                console.print("[yellow]No existing projects found. Starting a new project.[/yellow]")
                choice = "1"
            else:
                table = Table(show_header=True, header_style="bold magenta", box=None)
                table.add_column("No.")
                table.add_column("Project ID")
                table.add_column("Name")
                table.add_column("In Tokens")
                table.add_column("Out Tokens")
                
                proj_list = list(projects.items())
                for i, (pid, pdata) in enumerate(proj_list, 1):
                    in_toks = str(pdata.get("input_tokens", 0))
                    out_toks = str(pdata.get("output_tokens", 0))
                    table.add_row(f"[bold cyan]{i}.[/bold cyan]", pid, pdata["name"], f"[cyan]{in_toks}[/cyan]", f"[cyan]{out_toks}[/cyan]")
                console.print(Panel(table, title="Existing Projects", border_style="blue", expand=False))
                
                sel = Prompt.ask(f"Select a project [1-{len(proj_list)}]")
                try:
                    idx = int(sel) - 1
                    if 0 <= idx < len(proj_list):
                        project_id = proj_list[idx][0]
                    else:
                        console.print("[yellow]Invalid choice. Creating new project.[/yellow]")
                        choice = "1"
                except ValueError:
                    console.print("[yellow]Invalid choice. Creating new project.[/yellow]")
                    choice = "1"
                    
                if project_id:
                    console.print(f"[bold green]Loaded project:[/bold green] {projects[project_id]['name']} ({project_id})")
                    
        if choice == "1" or not project_id:
            proj_name = Prompt.ask("Enter new project name", default="Untitled Project")
            project_id = db.create_project(proj_name)
            console.print(f"[bold green]Started new project:[/bold green] {proj_name} ({project_id})")
                
        console.print()
        providers_dict = config.get("cloud_providers", {})
        available_providers = [k for k in providers_dict.keys() if k != "default"]
        current_default = providers_dict.get("default")
        if current_default not in available_providers and available_providers:
            current_default = available_providers[0]
            
        selected_provider = Prompt.ask(
            "Select Cloud LLM Fallback for this session (⚠️ Tip: Choose a model with strong tool/JSON support)", 
            choices=available_providers, 
            default=current_default
        )
        if "cloud_providers" not in config:
            config["cloud_providers"] = {}
        config["cloud_providers"]["default"] = selected_provider
            
        with console.status("[bold green]Initializing components..."):
            try:
                engine = create_engine_from_config(config_path)
                if not engine.verify():
                    console.print("[bold red]Error:[/bold red] Local LLM runtime not found.")
                    return
                    
                tiny_llm = TinyLLM(engine)
                cloud_provider = create_cloud_provider(config)
                
                # Validate the cloud provider
                is_valid, msg = cloud_provider.verify()
                if not is_valid:
                    current_provider = config.get("cloud_providers", {}).get("default", "mock")
                    if current_provider == "mock":
                        console.print(f"\n[bold yellow]⚠️  Note:[/bold yellow] You are currently using the 'mock' cloud provider.")
                        console.print("[dim]Escalations will return simulated responses. Use Option 3 in the Main Menu to configure a real API key (e.g., OpenRouter, OpenAI, Ollama).[/dim]\n")
                    else:
                        console.print(f"\n[bold red]⚠️  Warning:[/bold red] Cloud provider '{current_provider}' is not properly configured!")
                        console.print(f"[red]Reason:[/red] {msg}")
                        console.print("[dim]Cloud escalations will fail. You can fix this by using Option 3 in the Main Menu.[/dim]\n")
                
                from ecogent_experiment.agents.os_agent import OSAgent
                from ecogent_experiment.agents.browser_agent import BrowserAgent
                
                os_agent = OSAgent()
                browser_agent = BrowserAgent(cloud_provider=cloud_provider)

                # Seed builtin web tools into registry so they are found by semantic search
                from ecogent_experiment.tool_registry import ToolRegistry as _TR
                _tr_seed = _TR(os.path.join(root, "data", "chroma"))
                for _wt in [
                    ("web_search", "Web Search", "search the web, search google, search bing, find information online, web query", "browser_agent"),
                    ("browse_website", "Browse Website", "open a url, browse a website, visit a page, scrape a site, navigate to http", "browser_agent"),
                    ("browser_scrape", "Browser Scrape", "scrape a webpage, crawl a site, read website content, fetch url", "browser_agent"),
                ]:
                    _tr_seed.register_tool(
                        tool_key=_wt[0], natural_name=_wt[1], description=_wt[2],
                        category="web", agent=_wt[3], execution="local",
                        persistent=True, collection="builtin_tools",
                    )

                # Inject cloud_provider to real_executor so it can pass ask_llm + file_path
                def real_executor(tool_name, **kwargs):
                    task = kwargs.pop("task", "")
                    agent_name = kwargs.pop("agent_used", "os_agent")
                    file_path = kwargs.pop("file_path", None)

                    # Provide an LLM callback for mid-step communication
                    kwargs["ask_llm"] = lambda prompt: cloud_provider.generate_plan(prompt).get("answer", "")

                    if agent_name == "browser_agent":
                        return browser_agent.execute(
                            task, tool_key=tool_name, project_id=project_id,
                            file_path=file_path, **kwargs
                        )
                    else:
                        return os_agent.execute(
                            task, tool_key=tool_name, project_id=project_id,
                            file_path=file_path, **kwargs
                        )
                    
                supervisor = Supervisor(tiny_llm=tiny_llm, confidence_threshold=config.get("supervisor", {}).get("confidence_threshold", 0.7))
                router = Router(tool_executor=real_executor, cloud_provider=cloud_provider, tiny_llm=tiny_llm)
            except Exception as e:
                console.print(f"[bold red]Initialization Error:[/bold red] {e}")
                continue
                
        console.print(f"[dim]Ready. Cloud fallback: {config.get('cloud_providers', {}).get('default', 'mock')}[/dim]")
        console.print("[dim]Type 'back', 'menu', or 'exit' to return to the main menu.[/dim]")
        console.print("[dim]" + "─" * 60 + "[/dim]")
        
        # Initialize token counts from the project database if it exists
        proj_data = db.get_project(project_id) if project_id else {}
        total_input = proj_data.get("input_tokens", 0)
        total_output = proj_data.get("output_tokens", 0)
        
        while True:
            try:
                console.print()
                user_input = Prompt.ask(f"[bold cyan][{project_id}][/bold cyan] >")
                
                if not user_input.strip():
                    continue
                if user_input.lower() in ["exit", "quit", "back", "menu"]:
                    console.print("[dim]Returning to main menu...[/dim]")
                    break
                    
                db.append_chat(project_id, {"role": "user", "content": user_input})
                
                # ══════════════════════════════════════════════════════════
                # LOCAL-FIRST PIPELINE — Every request starts here
                # ══════════════════════════════════════════════════════════
                from ecogent_experiment.local_executor import execute_local_first
                from ecogent_experiment.tool_registry import ToolRegistry

                tool_registry = ToolRegistry(os.path.join(root, "data", "chroma"))

                # Ensure builtin tools are loaded for direct execution
                from ecogent_experiment.lc_tools import get_all_tools, get_tool_descriptions
                ask_llm_fn = lambda p: cloud_provider.generate_plan(p).get("answer", "")
                lc_tools = get_all_tools(ask_llm=ask_llm_fn)

                # Register tools in Chroma (idempotent)
                for td in get_tool_descriptions(lc_tools):
                    tool_registry.register_tool(
                        tool_key=td["tool_key"],
                        natural_name=td["natural_name"],
                        description=td["description"],
                        category=td.get("category", "builtin"),
                        agent=td.get("agent", "os_agent"),
                        persistent=True,
                        collection="builtin_tools",
                    )

                # ── Run through local-first pipeline ──
                local_result = execute_local_first(
                    user_input=user_input,
                    supervisor=supervisor,
                    tool_registry=tool_registry,
                    lc_tools=lc_tools,
                    tiny_llm=tiny_llm,
                    cloud_provider=cloud_provider,
                    project_id=project_id,
                    console=console,
                )

                if not local_result.cloud_escalated:
                    # ── Simple task completed locally ──
                    class LocalMockResult:
                        def __init__(self, lr):
                            self.output = lr.output
                            self.estimated_input_tokens = lr.estimated_input_tokens
                            self.estimated_output_tokens = lr.estimated_output_tokens
                    result = LocalMockResult(local_result)

                else:
                    # ══════════════════════════════════════════════════════
                    # CLOUD PATH — Complex tasks only
                    # ══════════════════════════════════════════════════════
                    accum_input = 0
                    accum_output = 0

                    # ── Browser Recording Mode ─────────────────────────────
                    # If local_executor detected a browser automation task
                    # with no existing pattern, handle it here directly.
                    _esc_ctx = getattr(local_result, "cloud_escalation_context", None) or {}
                    if _esc_ctx.get("mode") == "browser_recording":
                        console.print("\n[bold cyan]=== BROWSER RECORDING MODE ===[/bold cyan]")
                        console.print("[dim]No saved pattern found. Recording a new workflow step-by-step...[/dim]")
                        try:
                            from ecogent_experiment.browser_workflow.manager import BrowserWorkflowManager
                            _bwm = BrowserWorkflowManager(
                                project_id=project_id,
                                chroma_dir=os.path.join(root, "data", "chroma"),
                                projects_dir=os.path.join(root, "projects"),
                                cloud_provider=cloud_provider,
                            )
                            _bw_result = _bwm.run(
                                task=user_input,
                                variables={},
                                console=console,
                            )
                            class _BwMockResult:
                                def __init__(self, r):
                                    self.output = r.summary
                                    self.estimated_input_tokens = r.cloud_calls * 800
                                    self.estimated_output_tokens = r.cloud_calls * 400
                            result = _BwMockResult(_bw_result)
                        except Exception as _bwe:
                            console.print(f"[red]Browser recording failed:[/red] {_bwe}")
                            class _ErrResult:
                                output = f"Browser task failed: {_bwe}"
                                estimated_input_tokens = 0
                                estimated_output_tokens = 0
                            result = _ErrResult()
                        # Skip the rest of the cloud path for browser tasks
                        output_text = result.output
                        if isinstance(output_text, dict):
                            output_text = output_text.get("answer", str(output_text))
                        elif not isinstance(output_text, str):
                            output_text = str(output_text)
                        agent_panel = Panel(
                            Markdown(output_text),
                            title="🤖 Ecogent Agent [Browser]",
                            border_style="green",
                            padding=(1, 2)
                        )
                        console.print()
                        console.print(agent_panel)
                        db.append_chat(project_id, {"role": "assistant", "content": output_text})
                        total_input += result.estimated_input_tokens
                        total_output += result.estimated_output_tokens
                        db.update_metrics(project_id, result.estimated_input_tokens, result.estimated_output_tokens)
                        metrics_text = f"[dim]Tokens — Input: [cyan]{total_input}[/cyan] | Output: [cyan]{total_output}[/cyan][/dim]"
                        console.print(metrics_text, justify="right")
                        continue  # Back to user input prompt

                    # ── Standard Cloud Path ────────────────────────────────
                    console.print("\n[bold yellow]=== CLOUD ESCALATION: Complex task requires planning ===[/bold yellow]")
                    console.print("[dim]Checking memory for similar past workflows...[/dim]")

                    past_plans = tool_registry.query_workflow_memory(user_input, n_results=1)
                    workflow_tree_data = None

                    if past_plans and past_plans[0].get("distance", 1.0) < 0.3:
                        console.print(f"[green]Found similar past plan![/green] (Distance: {past_plans[0]['distance']:.2f})")
                        try:
                            workflow_tree_data = json.loads(past_plans[0]["plan_json"])
                        except Exception:
                            pass

                    if not workflow_tree_data:
                        console.print("[dim]No matching plan found. Contacting Cloud LLM to generate Plan.json...[/dim]")
                        
                        # Pass context about pattern-based browser automation to LLM
                        llm_input = user_input
                        llm_input += "\n\n[SYSTEM NOTE: If this request requires browser automation (e.g. going to a website and extracting data or filling forms), DO NOT generate a custom multi-step workflow. We have a pattern-based Playwright system for this. Instead, generate a plan with a SINGLE step that calls the `browser_task` tool.]"

                        workflow_tree_data, plan_res = cloud_provider.generate_workflow_tree(llm_input)
                        accum_input += plan_res.get("input_tokens", 0)
                        accum_output += plan_res.get("output_tokens", 0)
                        tool_registry.save_workflow_memory(project_id, user_input, json.dumps(workflow_tree_data))


                    from ecogent_experiment.workflow import WorkflowEngine
                    wf_engine = WorkflowEngine(os.path.join(root, "data", "workflows"))
                    workflow = wf_engine.create_workflow(
                        db.get_project(project_id).get("name", "Unknown"),
                        workflow_tree_data, project_id,
                    )
                    console.print(f"[bold cyan]Plan Generated with {len(workflow.project_tree)} steps.[/bold cyan]")

                    from ecogent_experiment.agent import EcogentAgent
                    from ecogent_experiment.context import ContextManager

                    ecogent_agent = EcogentAgent(
                        cloud_provider=cloud_provider,
                        lc_tools=lc_tools,
                        tiny_llm=tiny_llm,
                        verbose=True,
                    )

                    chat_file = os.path.join(root, db.get_project(project_id)["chat_history_file"])
                    workspace_dir = None
                    try:
                        with open(chat_file, "r", encoding="utf-8") as f:
                            chat_data = json.load(f)
                            if "workspace_dir" in chat_data:
                                workspace_dir = os.path.abspath(os.path.join(root, chat_data["workspace_dir"]))
                    except Exception:
                        pass
                    
                    if not workspace_dir:
                        project_name = db.get_project(project_id).get("name", "Unknown")
                        workspace_dir = os.path.join(root, "output", project_name)
                        os.makedirs(workspace_dir, exist_ok=True)
                        
                    console.print(f"[dim]Workspace directory set to: {workspace_dir}[/dim]")

                    ctx_mgr = ContextManager(
                        user_task=user_input,
                        project_id=project_id,
                        workspace_dir=workspace_dir,
                    )
                    step_results = {}

                    console.print("\n[bold blue]=== Execution Loop (Agent + Tiny LLM) ===[/bold blue]")

                    for step_idx, node in enumerate(workflow.project_tree, 1):
                        console.print(f"\n  [bold yellow]Step {step_idx}/{len(workflow.project_tree)}:[/bold yellow] {node.task_title}")

                        candidates_db = tool_registry.search_all_collections(node.task_title, n_results=8)
                        available_tool_keys = [c["tool_key"] for c in candidates_db] if candidates_db else []
                        
                        # Always ensure core OS/File tools are available during complex execution
                        core_tools = ["write_file", "read_file", "run_shell", "list_directory"]
                        for ct in core_tools:
                            if ct not in available_tool_keys:
                                available_tool_keys.append(ct)
                                
                        console.print(f"  [dim]↳ Tools: {available_tool_keys}[/dim]")

                        lc_tool_dicts = [
                            {"tool_key": t.name, "description": t.description, "agent": "os_agent"}
                            for t in lc_tools
                        ]
                        packet = ctx_mgr.build_packet(
                            step_n=step_idx,
                            total_steps=len(workflow.project_tree),
                            step_goal=node.task_title,
                            available_tools=lc_tool_dicts,
                        )

                        step_out = ecogent_agent.run_step(packet, available_tool_keys=available_tool_keys)
                        result_str = step_out["result"]
                        tool_used = step_out.get("tool_used", "unknown")
                        path = step_out.get("path", "react_agent")
                        accum_input += step_out.get("input_tokens", 0)
                        accum_output += step_out.get("output_tokens", 0)

                        ctx_mgr.record_result(node.task_title, result_str)
                        step_results[node.node_id] = result_str

                        verified = step_out.get("verified", True)
                        status_icon = "[green]✓[/green]" if verified else "[yellow]~[/yellow]"
                        path_tag = "[dim](tiny_llm)[/dim]" if path == "tiny_llm_direct" else "[dim](react)[/dim]"
                        tool_tag = f"[dim]tool: {tool_used}[/dim]" if tool_used else ""
                        console.print(f"  {status_icon} Step done {path_tag} {tool_tag}")

                        wf_engine.update_node(workflow, node.node_id, "completed", result=result_str)

                    wf_engine.save_workflow(workflow)

                    # Final answer synthesis — use results directly if possible
                    results_summary = ctx_mgr.get_results_summary(max_chars_per_step=1500)

                    # Try deterministic: if only 1 step and it succeeded, use its result directly
                    if len(workflow.project_tree) == 1 and step_results:
                        final_answer = list(step_results.values())[0]
                    else:
                        # Multi-step: synthesize with Cloud LLM
                        verify_prompt = (
                            f"User request: '{user_input}'\n"
                            f"Executed {len(workflow.project_tree)} steps. Results:\n\n"
                            f"{results_summary}\n\n"
                            f"CRITICAL: Answer the user's request USING ONLY THE RESULTS ABOVE."
                        )
                        final_res = cloud_provider.generate_plan(verify_prompt)
                        accum_input += final_res.get("input_tokens", 0)
                        accum_output += final_res.get("output_tokens", 0)
                        final_answer = final_res["answer"]

                    class MockResult:
                        def __init__(self, out, i_tok, o_tok):
                            self.output = out
                            self.estimated_input_tokens = i_tok
                            self.estimated_output_tokens = o_tok
                    result = MockResult(final_answer, accum_input, accum_output)
                
                # 3. Output
                output_text = result.output
                if isinstance(output_text, dict):
                    output_text = output_text.get("answer", str(output_text))
                elif not isinstance(output_text, str):
                    output_text = str(output_text)
                    
                agent_panel = Panel(
                    Markdown(output_text), 
                    title="🤖 Ecogent Agent", 
                    border_style="green",
                    padding=(1, 2)
                )
                console.print()
                console.print(agent_panel)
                db.append_chat(project_id, {"role": "assistant", "content": output_text})
                
                # 4. Metrics
                total_input += result.estimated_input_tokens
                total_output += result.estimated_output_tokens
                db.update_metrics(project_id, result.estimated_input_tokens, result.estimated_output_tokens)
                
                metrics_text = f"[dim]Tokens — Input: [cyan]{total_input}[/cyan] | Output: [cyan]{total_output}[/cyan][/dim]"
                console.print(metrics_text, justify="right")
                
            except KeyboardInterrupt:
                console.print("\n[dim]Type 'back' to return to menu.[/dim]")
            except EOFError:
                break

if __name__ == "__main__":
    cli()
