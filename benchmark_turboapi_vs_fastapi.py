"""
TurboAPI v0.4.0 vs FastAPI - Head-to-Head Performance Comparison
Tests identical endpoints on both frameworks with wrk load testing
"""

import subprocess
import time
import sys
import json
import os
import signal
from pathlib import Path

# ANSI color codes (matching original benchmark style)
CYAN = '\033[96m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
MAGENTA = '\033[95m'
BOLD = '\033[1m'
RESET = '\033[0m'

def print_header(text):
    print(f"\n{BOLD}{CYAN}{'=' * 80}{RESET}")
    print(f"{BOLD}{CYAN}{text.center(80)}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 80}{RESET}\n")

def print_section(text):
    print(f"\n{BOLD}{MAGENTA}{'▶ ' + text}{RESET}")
    print(f"{MAGENTA}{'-' * (len(text) + 2)}{RESET}")

def run_wrk(url, threads=4, connections=50, duration=10):
    """Run wrk benchmark and parse results"""
    cmd = f"wrk -t{threads} -c{connections} -d{duration}s {url}"
    
    try:
        result = subprocess.run(
            cmd.split(),
            capture_output=True,
            text=True,
            timeout=duration + 5
        )
        
        output = result.stdout
        
        # Parse results
        rps = 0
        latency_avg = 0
        
        for line in output.split('\n'):
            if 'Requests/sec:' in line:
                rps = float(line.split(':')[1].strip())
            elif 'Latency' in line and 'Stdev' not in line:
                parts = line.split()
                if len(parts) >= 2:
                    latency_str = parts[1]
                    # Convert to ms
                    if 'ms' in latency_str:
                        latency_avg = float(latency_str.replace('ms', ''))
                    elif 'us' in latency_str:
                        latency_avg = float(latency_str.replace('us', '')) / 1000
                    elif 's' in latency_str:
                        latency_avg = float(latency_str.replace('s', '')) * 1000
        
        return {'rps': rps, 'latency': latency_avg}
    except Exception as e:
        print(f"{RED}Error: {e}{RESET}")
        return None

def format_number(num):
    """Format number with commas"""
    return f"{num:,.0f}"

def print_comparison(name, turbo_result, fastapi_result):
    """Print side-by-side comparison"""
    if not turbo_result or not fastapi_result:
        print(f"{RED}  ✗ {name}: Failed{RESET}")
        return
    
    turbo_rps = turbo_result['rps']
    fastapi_rps = fastapi_result['rps']
    speedup = turbo_rps / fastapi_rps if fastapi_rps > 0 else 0
    
    turbo_lat = turbo_result['latency']
    fastapi_lat = fastapi_result['latency']
    
    print(f"\n{BOLD}{name}:{RESET}")
    print(f"  {CYAN}TurboAPI:{RESET}  {BOLD}{format_number(turbo_rps):>10}{RESET} req/s  ({turbo_lat:.2f}ms latency)")
    print(f"  {YELLOW}FastAPI:{RESET}   {format_number(fastapi_rps):>10} req/s  ({fastapi_lat:.2f}ms latency)")
    
    if speedup >= 1:
        print(f"  {BOLD}{GREEN}Speedup:{RESET}    {BOLD}{speedup:.1f}x faster{RESET} ⚡")
    else:
        print(f"  {BOLD}{RED}Speedup:{RESET}    {1/speedup:.1f}x slower")

# Test server code
TURBOAPI_SERVER = '''
from turboapi import TurboAPI
import asyncio

app = TurboAPI()

@app.get("/")
def root():
    return {"message": "Hello TurboAPI"}

@app.get("/users/{user_id}")
def get_user(user_id: int):
    return {"user_id": user_id, "name": f"User {user_id}"}

@app.get("/search")
def search(q: str, limit: int = 10):
    return {"query": q, "limit": limit}

@app.get("/async")
async def async_endpoint():
    await asyncio.sleep(0.001)
    return {"message": "Async TurboAPI"}

app.run(host="127.0.0.1", port=8001)
'''

FASTAPI_SERVER = '''
from fastapi import FastAPI
import uvicorn
import asyncio

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Hello FastAPI"}

@app.get("/users/{user_id}")
def get_user(user_id: int):
    return {"user_id": user_id, "name": f"User {user_id}"}

@app.get("/search")
def search(q: str, limit: int = 10):
    return {"query": q, "limit": limit}

@app.get("/async")
async def async_endpoint():
    await asyncio.sleep(0.001)
    return {"message": "Async FastAPI"}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8002, log_level="error")
'''

def main():
    print_header("TurboAPI v0.4.0 vs FastAPI - Performance Comparison")
    
    print(f"{BOLD}Test Configuration:{RESET}")
    print(f"  Duration: 10 seconds per test")
    print(f"  Connections: 50 (light load)")
    print(f"  Threads: 4")
    print(f"  Tool: wrk (HTTP benchmarking)")
    
    # Check if wrk is installed
    try:
        result = subprocess.run(["wrk", "--version"], capture_output=True, text=True)
        if result.returncode != 0 and result.returncode != 1:  # wrk returns 1 for --version
            raise FileNotFoundError
        print(f"{GREEN}  ✓ wrk available{RESET}")
    except FileNotFoundError:
        print(f"\n{RED}✗ wrk not installed. Install with: brew install wrk{RESET}")
        return
    
    print_section("Starting Test Servers")
    
    # Write server files
    turbo_file = Path("_turboapi_bench_server.py")
    fastapi_file = Path("_fastapi_bench_server.py")
    
    turbo_file.write_text(TURBOAPI_SERVER)
    fastapi_file.write_text(FASTAPI_SERVER)
    
    # Start servers
    print(f"  Starting TurboAPI on port 8001...")
    turbo_proc = subprocess.Popen(
        [sys.executable, str(turbo_file)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(3)
    
    print(f"  Starting FastAPI on port 8002...")
    fastapi_proc = subprocess.Popen(
        [sys.executable, str(fastapi_file)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(3)
    
    # Verify servers are running
    try:
        import requests
        requests.get("http://localhost:8001/", timeout=2)
        requests.get("http://localhost:8002/", timeout=2)
        print(f"{GREEN}  ✓ Both servers running{RESET}")
    except:
        print(f"{RED}  ✗ Failed to start servers{RESET}")
        turbo_proc.kill()
        fastapi_proc.kill()
        return
    
    # Run benchmarks
    tests = [
        ("Root Endpoint", "/"),
        ("Path Parameters", "/users/123"),
        ("Query Parameters", "/search?q=test&limit=10"),
        ("Async Endpoint", "/async"),
    ]
    
    results = {}
    
    for test_name, path in tests:
        print_section(f"Testing: {test_name}")
        
        print(f"  Running TurboAPI benchmark...")
        turbo_result = run_wrk(f"http://localhost:8001{path}")
        
        print(f"  Running FastAPI benchmark...")
        fastapi_result = run_wrk(f"http://localhost:8002{path}")
        
        print_comparison(test_name, turbo_result, fastapi_result)
        
        results[test_name] = {
            'turboapi': turbo_result,
            'fastapi': fastapi_result,
            'speedup': turbo_result['rps'] / fastapi_result['rps'] if turbo_result and fastapi_result and fastapi_result['rps'] > 0 else 0
        }
    
    # Summary
    print_section("Performance Summary")
    
    total_speedup = sum(r['speedup'] for r in results.values() if r['speedup'] > 0)
    avg_speedup = total_speedup / len(results) if results else 0
    
    print(f"\n{BOLD}Average Speedup:{RESET} {BOLD}{GREEN}{avg_speedup:.1f}x faster{RESET}")
    
    # Find best performance
    best_test = max(results.items(), key=lambda x: x[1]['speedup'])
    print(f"{BOLD}Best Performance:{RESET} {best_test[0]} - {BOLD}{GREEN}{best_test[1]['speedup']:.1f}x faster{RESET}")
    
    # Cleanup
    print_section("Cleanup")
    print(f"  Stopping servers...")
    turbo_proc.kill()
    fastapi_proc.kill()
    turbo_file.unlink()
    fastapi_file.unlink()
    print(f"{GREEN}  ✓ Cleanup complete{RESET}")
    
    # Save results
    results_file = Path("benchmark_comparison_results.json")
    json_results = {}
    for test, data in results.items():
        json_results[test] = {
            'turboapi_rps': data['turboapi']['rps'] if data['turboapi'] else 0,
            'fastapi_rps': data['fastapi']['rps'] if data['fastapi'] else 0,
            'speedup': data['speedup']
        }
    
    with open(results_file, 'w') as f:
        json.dump({
            'version': '0.4.0',
            'avg_speedup': avg_speedup,
            'results': json_results
        }, f, indent=2)
    
    print(f"\n{GREEN}Results saved to: {results_file}{RESET}")
    
    print_header("Benchmark Complete!")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}Benchmark interrupted{RESET}")
        # Cleanup any running servers
        subprocess.run(["pkill", "-f", "_turboapi_bench_server.py"], stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-f", "_fastapi_bench_server.py"], stderr=subprocess.DEVNULL)
        sys.exit(1)
