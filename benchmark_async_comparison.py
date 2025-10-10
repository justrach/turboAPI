#!/usr/bin/env python3
"""
Benchmark: TurboAPI vs FastAPI - Async Routes Performance
Tests both sync and async endpoints under load with wrk
"""

import subprocess
import time
import sys
import json
from pathlib import Path

# ANSI colors
GREEN = "\033[92m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

def print_header(text):
    print(f"\n{BOLD}{BLUE}{'='*60}{RESET}")
    print(f"{BOLD}{BLUE}{text:^60}{RESET}")
    print(f"{BOLD}{BLUE}{'='*60}{RESET}\n")

def print_section(text):
    print(f"\n{BOLD}{YELLOW}▶ {text}{RESET}")

def check_wrk():
    """Check if wrk is installed"""
    try:
        result = subprocess.run(["wrk", "--version"], capture_output=True)
        # wrk returns exit code 1 even for --version, so just check if it ran
        return True
    except FileNotFoundError:
        print(f"{RED}❌ wrk not found! Install with: brew install wrk{RESET}")
        return False

def create_turboapi_server():
    """Create TurboAPI test server"""
    code = '''
import asyncio
from turboapi import TurboAPI

app = TurboAPI(title="TurboAPI Benchmark", version="1.0.0")

@app.get("/sync")
def sync_endpoint():
    """Sync endpoint - minimal processing"""
    return {"framework": "TurboAPI", "type": "sync", "status": "ok"}

@app.get("/async")
async def async_endpoint():
    """Async endpoint - with async sleep"""
    await asyncio.sleep(0.001)  # 1ms async delay
    return {"framework": "TurboAPI", "type": "async", "status": "ok"}

@app.get("/health")
def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    print("🚀 Starting TurboAPI server on http://127.0.0.1:8000")
    app.run(host="127.0.0.1", port=8000)
'''
    
    with open("benchmark_turboapi_server.py", "w") as f:
        f.write(code)
    
    return "benchmark_turboapi_server.py"

def create_fastapi_server():
    """Create FastAPI test server"""
    code = '''
import asyncio
import uvicorn
from fastapi import FastAPI

app = FastAPI(title="FastAPI Benchmark", version="1.0.0")

@app.get("/sync")
def sync_endpoint():
    """Sync endpoint - minimal processing"""
    return {"framework": "FastAPI", "type": "sync", "status": "ok"}

@app.get("/async")
async def async_endpoint():
    """Async endpoint - with async sleep"""
    await asyncio.sleep(0.001)  # 1ms async delay
    return {"framework": "FastAPI", "type": "async", "status": "ok"}

@app.get("/health")
def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    print("🚀 Starting FastAPI server on http://127.0.0.1:8001")
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="error")
'''
    
    with open("benchmark_fastapi_server.py", "w") as f:
        f.write(code)
    
    return "benchmark_fastapi_server.py"

def start_server(script_path, name, port):
    """Start a server and wait for it to be ready"""
    print_section(f"Starting {name} server...")
    
    process = subprocess.Popen(
        [sys.executable, script_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait for server to be ready
    max_wait = 10
    for i in range(max_wait):
        try:
            result = subprocess.run(
                ["curl", "-s", f"http://127.0.0.1:{port}/health"],
                capture_output=True,
                timeout=1
            )
            if result.returncode == 0:
                print(f"{GREEN}✅ {name} server ready on port {port}{RESET}")
                return process
        except:
            pass
        time.sleep(1)
    
    print(f"{RED}❌ {name} server failed to start{RESET}")
    process.kill()
    return None

def run_wrk_benchmark(url, endpoint_name, threads=4, connections=100, duration=10):
    """Run wrk benchmark and parse results"""
    print_section(f"Benchmarking {endpoint_name}...")
    print(f"  URL: {url}")
    print(f"  Threads: {threads}, Connections: {connections}, Duration: {duration}s")
    
    cmd = [
        "wrk",
        "-t", str(threads),
        "-c", str(connections),
        "-d", f"{duration}s",
        "--latency",
        url
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stdout
    
    # Parse results
    results = {
        "requests_per_sec": 0,
        "avg_latency_ms": 0,
        "p99_latency_ms": 0,
        "transfer_per_sec": "",
    }
    
    for line in output.split("\n"):
        if "Requests/sec:" in line:
            results["requests_per_sec"] = float(line.split()[1])
        elif "Transfer/sec:" in line:
            results["transfer_per_sec"] = line.split()[1]
        elif "Latency" in line and "%" not in line:
            # Parse avg latency
            parts = line.split()
            if len(parts) >= 2:
                latency_str = parts[1]
                if "ms" in latency_str:
                    results["avg_latency_ms"] = float(latency_str.replace("ms", ""))
                elif "us" in latency_str:
                    results["avg_latency_ms"] = float(latency_str.replace("us", "")) / 1000
        elif "99%" in line:
            # Parse p99 latency
            parts = line.split()
            if len(parts) >= 2:
                latency_str = parts[1]
                if "ms" in latency_str:
                    results["p99_latency_ms"] = float(latency_str.replace("ms", ""))
                elif "us" in latency_str:
                    results["p99_latency_ms"] = float(latency_str.replace("us", "")) / 1000
    
    print(f"{GREEN}  ✅ RPS: {results['requests_per_sec']:,.0f}{RESET}")
    print(f"  📊 Avg Latency: {results['avg_latency_ms']:.2f}ms")
    print(f"  📊 P99 Latency: {results['p99_latency_ms']:.2f}ms")
    
    return results

def print_comparison(turbo_results, fastapi_results, endpoint_type):
    """Print comparison table"""
    print_header(f"{endpoint_type.upper()} Endpoint Comparison")
    
    turbo_rps = turbo_results["requests_per_sec"]
    fastapi_rps = fastapi_results["requests_per_sec"]
    speedup = turbo_rps / fastapi_rps if fastapi_rps > 0 else 0
    
    turbo_latency = turbo_results["avg_latency_ms"]
    fastapi_latency = fastapi_results["avg_latency_ms"]
    latency_improvement = ((fastapi_latency - turbo_latency) / fastapi_latency * 100) if fastapi_latency > 0 else 0
    
    print(f"{BOLD}{'Metric':<25} {'TurboAPI':>15} {'FastAPI':>15} {'Improvement':>15}{RESET}")
    print("-" * 72)
    print(f"{'Requests/sec':<25} {turbo_rps:>15,.0f} {fastapi_rps:>15,.0f} {speedup:>14.2f}x")
    print(f"{'Avg Latency (ms)':<25} {turbo_latency:>15.2f} {fastapi_latency:>15.2f} {latency_improvement:>14.1f}%")
    print(f"{'P99 Latency (ms)':<25} {turbo_results['p99_latency_ms']:>15.2f} {fastapi_results['p99_latency_ms']:>15.2f}")
    print(f"{'Transfer/sec':<25} {turbo_results['transfer_per_sec']:>15} {fastapi_results['transfer_per_sec']:>15}")
    
    if speedup >= 5:
        print(f"\n{GREEN}{BOLD}🚀 TurboAPI is {speedup:.1f}x FASTER! 🚀{RESET}")
    elif speedup >= 2:
        print(f"\n{GREEN}{BOLD}✅ TurboAPI is {speedup:.1f}x faster{RESET}")
    else:
        print(f"\n{YELLOW}⚠️  TurboAPI is {speedup:.1f}x faster{RESET}")

def main():
    print_header("TurboAPI vs FastAPI - Async Benchmark")
    
    # Check prerequisites
    if not check_wrk():
        return 1
    
    # Create server scripts
    print_section("Creating benchmark servers...")
    turbo_script = create_turboapi_server()
    fastapi_script = create_fastapi_server()
    print(f"{GREEN}✅ Server scripts created{RESET}")
    
    # Benchmark configuration
    THREADS = 4
    CONNECTIONS = 100
    DURATION = 10
    
    print(f"\n{BOLD}Benchmark Configuration:{RESET}")
    print(f"  Threads: {THREADS}")
    print(f"  Connections: {CONNECTIONS}")
    print(f"  Duration: {DURATION}s per test")
    
    try:
        # ========== TURBOAPI BENCHMARKS ==========
        print_header("TurboAPI Benchmarks")
        turbo_process = start_server(turbo_script, "TurboAPI", 8000)
        if not turbo_process:
            return 1
        
        time.sleep(2)  # Let server stabilize
        
        turbo_sync = run_wrk_benchmark(
            "http://127.0.0.1:8000/sync",
            "TurboAPI Sync",
            THREADS, CONNECTIONS, DURATION
        )
        
        time.sleep(2)
        
        turbo_async = run_wrk_benchmark(
            "http://127.0.0.1:8000/async",
            "TurboAPI Async",
            THREADS, CONNECTIONS, DURATION
        )
        
        print(f"\n{GREEN}✅ TurboAPI benchmarks complete{RESET}")
        turbo_process.kill()
        time.sleep(2)
        
        # ========== FASTAPI BENCHMARKS ==========
        print_header("FastAPI Benchmarks")
        fastapi_process = start_server(fastapi_script, "FastAPI", 8001)
        if not fastapi_process:
            return 1
        
        time.sleep(2)  # Let server stabilize
        
        fastapi_sync = run_wrk_benchmark(
            "http://127.0.0.1:8001/sync",
            "FastAPI Sync",
            THREADS, CONNECTIONS, DURATION
        )
        
        time.sleep(2)
        
        fastapi_async = run_wrk_benchmark(
            "http://127.0.0.1:8001/async",
            "FastAPI Async",
            THREADS, CONNECTIONS, DURATION
        )
        
        print(f"\n{GREEN}✅ FastAPI benchmarks complete{RESET}")
        fastapi_process.kill()
        
        # ========== COMPARISON ==========
        print_comparison(turbo_sync, fastapi_sync, "SYNC")
        print_comparison(turbo_async, fastapi_async, "ASYNC")
        
        # ========== FINAL SUMMARY ==========
        print_header("Final Summary")
        
        sync_speedup = turbo_sync["requests_per_sec"] / fastapi_sync["requests_per_sec"]
        async_speedup = turbo_async["requests_per_sec"] / fastapi_async["requests_per_sec"]
        avg_speedup = (sync_speedup + async_speedup) / 2
        
        print(f"{BOLD}Overall Performance:{RESET}")
        print(f"  Sync Speedup:  {sync_speedup:.2f}x")
        print(f"  Async Speedup: {async_speedup:.2f}x")
        print(f"  Average:       {avg_speedup:.2f}x")
        
        if avg_speedup >= 5:
            print(f"\n{GREEN}{BOLD}🎉🎉🎉 TurboAPI is {avg_speedup:.1f}x FASTER than FastAPI! 🎉🎉🎉{RESET}")
        elif avg_speedup >= 2:
            print(f"\n{GREEN}{BOLD}🚀 TurboAPI is {avg_speedup:.1f}x faster than FastAPI! 🚀{RESET}")
        else:
            print(f"\n{YELLOW}TurboAPI is {avg_speedup:.1f}x faster than FastAPI{RESET}")
        
        # Save results
        results = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "config": {
                "threads": THREADS,
                "connections": CONNECTIONS,
                "duration": DURATION
            },
            "turboapi": {
                "sync": turbo_sync,
                "async": turbo_async
            },
            "fastapi": {
                "sync": fastapi_sync,
                "async": fastapi_async
            },
            "speedup": {
                "sync": sync_speedup,
                "async": async_speedup,
                "average": avg_speedup
            }
        }
        
        with open("benchmark_results.json", "w") as f:
            json.dump(results, f, indent=2)
        
        print(f"\n{GREEN}✅ Results saved to benchmark_results.json{RESET}")
        
    except KeyboardInterrupt:
        print(f"\n{YELLOW}⚠️  Benchmark interrupted{RESET}")
        return 1
    except Exception as e:
        print(f"\n{RED}❌ Error: {e}{RESET}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        # Cleanup
        subprocess.run(["pkill", "-f", "benchmark_turboapi_server"], stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-f", "benchmark_fastapi_server"], stderr=subprocess.DEVNULL)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
