#!/usr/bin/env python
"""
Advanced client for the Multi-Model MLX API server.

This script demonstrates more advanced features:
- Concurrent requests to multiple models
- Benchmarking performance
- Switching between models dynamically
- Handling different model types (thinking vs. non-thinking)
"""

import requests
import json
import sys
import time
import argparse
import threading
import asyncio
import aiohttp
import os
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from concurrent.futures import ThreadPoolExecutor

# Default API URL
DEFAULT_API_URL = "http://localhost:8000"

# Create rich console
console = Console()

class ModelClient:
    """Advanced client for the Multi-Model MLX API."""
    
    def __init__(self, api_url=DEFAULT_API_URL):
        self.api_url = api_url
        self.models_cache = []
        self.session = requests.Session()
        
    def list_models(self):
        """List all available models."""
        response = self.session.get(f"{self.api_url}/v1/models")
        if response.status_code == 200:
            models = response.json()
            self.models_cache = models["data"]
            
            # Display models in a nice table
            table = Table(title="Available Models")
            table.add_column("ID", style="cyan")
            table.add_column("Created", style="green")
            table.add_column("Owner", style="blue")
            
            for model in models["data"]:
                # Convert timestamp to readable date
                created = datetime.fromtimestamp(model["created"]).strftime('%Y-%m-%d %H:%M:%S')
                table.add_row(model["id"], created, model["owned_by"])
            
            console.print(table)
            return models["data"]
        else:
            console.print(f"[red]Error listing models: {response.text}[/red]")
            return []
    
    def load_model(self, model_name, model_key=None):
        """Load a new model."""
        if model_key is None:
            model_key = model_name.split("/")[-1]
        
        url = f"{self.api_url}/v1/models/load"
        payload = {
            "model_name": model_name,
            "model_key": model_key
        }
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task(f"Loading model {model_name}...", total=None)
            
            response = self.session.post(url, json=payload)
            progress.update(task, completed=True)
            
            if response.status_code == 200:
                result = response.json()
                console.print(f"[green]Success: {result['message']}[/green]")
                return True
            else:
                console.print(f"[red]Error loading model: {response.text}[/red]")
                return False
    
    def unload_model(self, model_key):
        """Unload a model."""
        url = f"{self.api_url}/v1/models/unload"
        payload = {"model_key": model_key}
        
        response = self.session.post(url, json=payload)
        if response.status_code == 200:
            result = response.json()
            console.print(f"[green]Success: {result['message']}[/green]")
            return True
        else:
            console.print(f"[red]Error unloading model: {response.text}[/red]")
            return False
    
    def chat_completion(self, model, messages, max_tokens=1024, stream=False):
        """Send a chat completion request."""
        url = f"{self.api_url}/v1/chat/completions"
        
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": stream
        }
        
        start_time = time.time()
        
        if stream:
            # Streaming response
            response = self.session.post(url, json=payload, stream=True)
            if response.status_code != 200:
                console.print(f"[red]Error: {response.text}[/red]")
                return None
            
            # Process the streamed response
            console.print(f"\n[bold cyan]Model {model} response:[/bold cyan]")
            
            content = ""
            first_token_time = None
            
            for line in response.iter_lines():
                if line:
                    line_text = line.decode('utf-8')
                    if line_text.startswith("data: "):
                        if line_text == "data: [DONE]":
                            break
                        try:
                            data = json.loads(line_text[6:])  # Remove "data: " prefix
                            if "choices" in data and len(data["choices"]) > 0:
                                delta = data["choices"][0].get("delta", {})
                                if "content" in delta:
                                    # Record time of first token if not already set
                                    if first_token_time is None:
                                        first_token_time = time.time()
                                    
                                    content_chunk = delta["content"]
                                    content += content_chunk
                                    console.print(content_chunk, end="")
                        except json.JSONDecodeError:
                            console.print(f"[red]Error parsing JSON: {line_text}[/red]")
            
            end_time = time.time()
            
            # Report timing metrics
            total_time = end_time - start_time
            ttft = (first_token_time - start_time) if first_token_time else 0
            
            console.print()
            console.print(Panel(f"Time to first token: {ttft:.2f}s\nTotal time: {total_time:.2f}s", 
                               title="Streaming Performance", border_style="green"))
            
            return {
                "content": content,
                "timing": {
                    "total_time": total_time,
                    "ttft": ttft
                }
            }
        else:
            # Regular non-streaming response
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task(f"Generating with {model}...", total=None)
                
                response = self.session.post(url, json=payload)
                progress.update(task, completed=True)
            
            end_time = time.time()
            total_time = end_time - start_time
            
            if response.status_code == 200:
                result = response.json()
                
                # Extract and print the response
                content = result["choices"][0]["message"]["content"]
                console.print(Panel(content, title=f"Response from {model}", border_style="cyan"))
                
                # Check for thinking content
                if "_thinking" in result:
                    console.print(Panel(result["_thinking"], title="Thinking Process", border_style="yellow"))
                
                # Report timing metrics
                tokens = result["usage"]["completion_tokens"]
                tokens_per_second = tokens / total_time if total_time > 0 else 0
                
                metrics_table = Table(title="Performance Metrics")
                metrics_table.add_column("Metric", style="cyan")
                metrics_table.add_column("Value", style="green")
                
                metrics_table.add_row("Total time", f"{total_time:.2f}s")
                metrics_table.add_row("Completion tokens", str(tokens))
                metrics_table.add_row("Tokens per second", f"{tokens_per_second:.2f}")
                
                console.print(metrics_table)
                
                return {
                    "content": content,
                    "thinking": result.get("_thinking", ""),
                    "timing": {
                        "total_time": total_time,
                        "tokens": tokens,
                        "tokens_per_second": tokens_per_second
                    }
                }
            else:
                console.print(f"[red]Error: {response.text}[/red]")
                return None
    
    async def async_chat_completion(self, model, messages, max_tokens=1024):
        """Asynchronous chat completion."""
        url = f"{self.api_url}/v1/chat/completions"
        
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": False
        }
        
        start_time = time.time()
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    end_time = time.time()
                    
                    # Extract response content
                    content = result["choices"][0]["message"]["content"]
                    
                    return {
                        "model": model,
                        "content": content,
                        "thinking": result.get("_thinking", ""),
                        "timing": {
                            "total_time": end_time - start_time,
                            "tokens": result["usage"]["completion_tokens"],
                        }
                    }
                else:
                    error_text = await response.text()
                    console.print(f"[red]Error with {model}: {error_text}[/red]")
                    return {
                        "model": model,
                        "error": error_text
                    }
    
    async def compare_models(self, models, prompt, max_tokens=1024):
        """Compare multiple models with the same prompt."""
        messages = [{"role": "user", "content": prompt}]
        
        console.print(f"[bold]Comparing {len(models)} models with prompt:[/bold] {prompt}\n")
        
        # Create tasks for all models
        tasks = []
        for model in models:
            tasks.append(self.async_chat_completion(model, messages, max_tokens))
        
        # Run all tasks concurrently
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task(f"Running inference on {len(models)} models...", total=None)
            results = await asyncio.gather(*tasks)
            progress.update(task, completed=True)
        
        # Display results in a table
        comparison_table = Table(title="Model Comparison")
        comparison_table.add_column("Model", style="cyan")
        comparison_table.add_column("Total Time", style="green")
        comparison_table.add_column("Tokens", style="blue")
        
        for result in results:
            if "error" not in result:
                comparison_table.add_row(
                    result["model"],
                    f"{result['timing']['total_time']:.2f}s",
                    str(result['timing']['tokens'])
                )
        
        console.print(comparison_table)
        
        # Display detailed responses
        for result in results:
            if "error" not in result:
                console.print(Panel(
                    result["content"],
                    title=f"Response from {result['model']}",
                    border_style="cyan"
                ))
                
                # Show thinking if available
                if result.get("thinking"):
                    console.print(Panel(
                        result["thinking"],
                        title=f"Thinking from {result['model']}",
                        border_style="yellow"
                    ))
        
        return results
    
    def benchmark(self, model, prompts, max_tokens=1024):
        """Benchmark a model with multiple prompts."""
        results = []
        
        console.print(f"[bold]Benchmarking model {model} with {len(prompts)} prompts[/bold]\n")
        
        with Progress() as progress:
            benchmark_task = progress.add_task(f"Benchmarking {model}...", total=len(prompts))
            
            for i, prompt in enumerate(prompts):
                console.print(f"[bold]Prompt {i+1}:[/bold] {prompt[:50]}...")
                
                messages = [{"role": "user", "content": prompt}]
                
                start_time = time.time()
                result = self.chat_completion(model, messages, max_tokens)
                end_time = time.time()
                
                if result:
                    results.append({
                        "prompt": prompt,
                        "response": result["content"],
                        "thinking": result.get("thinking", ""),
                        "timing": result["timing"]
                    })
                
                progress.update(benchmark_task, advance=1)
        
        # Calculate aggregate metrics
        total_time = sum(r["timing"]["total_time"] for r in results)
        total_tokens = sum(r["timing"]["tokens"] for r in results)
        avg_time = total_time / len(results)
        avg_tokens = total_tokens / len(results)
        tokens_per_second = total_tokens / total_time if total_time > 0 else 0
        
        # Display summary metrics
        summary_table = Table(title=f"Benchmark Summary for {model}")
        summary_table.add_column("Metric", style="cyan")
        summary_table.add_column("Value", style="green")
        
        summary_table.add_row("Total prompts", str(len(prompts)))
        summary_table.add_row("Total time", f"{total_time:.2f}s")
        summary_table.add_row("Average time per prompt", f"{avg_time:.2f}s")
        summary_table.add_row("Total tokens", str(total_tokens))
        summary_table.add_row("Average tokens per prompt", f"{avg_tokens:.2f}")
        summary_table.add_row("Tokens per second", f"{tokens_per_second:.2f}")
        
        console.print(summary_table)
        
        return {
            "results": results,
            "summary": {
                "total_prompts": len(prompts),
                "total_time": total_time,
                "avg_time": avg_time,
                "total_tokens": total_tokens,
                "avg_tokens": avg_tokens,
                "tokens_per_second": tokens_per_second
            }
        }

def interactive_shell(client):
    """Run an interactive shell session with model switching."""
    console.print("[bold green]Interactive Multi-Model Chat Shell[/bold green]")
    console.print("Type commands or chat directly. Available commands:")
    console.print("  /models - List available models")
    console.print("  /model <name> - Switch to specified model")
    console.print("  /load <name> [key] - Load a new model")
    console.print("  /unload <key> - Unload a model")
    console.print("  /stream <on|off> - Toggle streaming mode")
    console.print("  /compare <model1,model2,...> - Compare models with same prompt")
    console.print("  /clear - Clear the screen")
    console.print("  /quit - Exit the shell")
    
    current_model = "qwq"  # Default model
    messages = []
    streaming = False
    
    while True:
        try:
            # Get user input
            user_input = console.input("\n[bold cyan]You[/bold cyan]: ")
            
            # Process commands
            if user_input.startswith("/"):
                parts = user_input.split()
                cmd = parts[0].lower()
                
                if cmd == "/models":
                    client.list_models()
                    continue
                
                elif cmd == "/model" and len(parts) > 1:
                    current_model = parts[1]
                    console.print(f"[green]Switched to model: {current_model}[/green]")
                    continue
                
                elif cmd == "/load" and len(parts) > 1:
                    model_name = parts[1]
                    model_key = parts[2] if len(parts) > 2 else None
                    client.load_model(model_name, model_key)
                    continue
                
                elif cmd == "/unload" and len(parts) > 1:
                    model_key = parts[1]
                    client.unload_model(model_key)
                    continue
                
                elif cmd == "/stream":
                    if len(parts) > 1 and parts[1].lower() in ["on", "off"]:
                        streaming = (parts[1].lower() == "on")
                        console.print(f"[green]Streaming mode: {'ON' if streaming else 'OFF'}[/green]")
                    else:
                        streaming = not streaming
                        console.print(f"[green]Streaming mode toggled: {'ON' if streaming else 'OFF'}[/green]")
                    continue
                
                elif cmd == "/compare" and len(parts) > 1:
                    models_to_compare = parts[1].split(",")
                    prompt = console.input("[bold yellow]Enter prompt for comparison: [/bold yellow]")
                    asyncio.run(client.compare_models(models_to_compare, prompt))
                    continue
                
                elif cmd == "/clear":
                    os.system('cls' if os.name == 'nt' else 'clear')
                    continue
                
                elif cmd == "/quit":
                    console.print("[bold red]Exiting chat shell.[/bold red]")
                    return
                
                else:
                    console.print("[red]Unknown command. Type /help for assistance.[/red]")
                    continue
            
            # Regular message - add to history
            messages.append({"role": "user", "content": user_input})
            
            # Get model response
            response = client.chat_completion(current_model, messages, stream=streaming)
            
            # Add to history if valid response
            if response and "content" in response:
                messages.append({"role": "assistant", "content": response["content"]})
        
        except KeyboardInterrupt:
            console.print("\n[bold red]Ctrl+C pressed. Type /quit to exit.[/bold red]")
        except Exception as e:
            console.print(f"[bold red]Error: {str(e)}[/bold red]")

def main():
    """Main function to run the advanced client."""
    parser = argparse.ArgumentParser(description="Advanced client for the Multi-Model MLX API")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="API server URL")
    parser.add_argument("--list", action="store_true", help="List available models")
    parser.add_argument("--load", help="Load a new model (provide model name)")
    parser.add_argument("--key", help="Custom key for loaded model")
    parser.add_argument("--unload", help="Unload a model (provide model key)")
    parser.add_argument("--compare", help="Compare multiple models (comma-separated list)")
    parser.add_argument("--benchmark", help="Model to benchmark")
    parser.add_argument("--prompt-file", help="File with prompts for benchmarking")
    parser.add_argument("--shell", action="store_true", help="Start interactive shell")
    
    args = parser.parse_args()
    
    # Create client
    client = ModelClient(args.api_url)
    
    # Handle commands
    if args.list:
        client.list_models()
    
    elif args.load:
        client.load_model(args.load, args.key)
    
    elif args.unload:
        client.unload_model(args.unload)
    
    elif args.compare:
        models = args.compare.split(",")
        prompt = console.input("[bold]Enter prompt for comparison: [/bold]")
        asyncio.run(client.compare_models(models, prompt))
    
    elif args.benchmark and args.prompt_file:
        # Read prompts from file
        try:
            with open(args.prompt_file, 'r') as f:
                prompts = [line.strip() for line in f if line.strip()]
                
            if prompts:
                client.benchmark(args.benchmark, prompts)
            else:
                console.print("[red]No prompts found in file.[/red]")
        except Exception as e:
            console.print(f"[red]Error reading prompt file: {str(e)}[/red]")
    
    elif args.shell:
        interactive_shell(client)
    
    else:
        # Default to interactive shell
        interactive_shell(client)

if __name__ == "__main__":
    main() 