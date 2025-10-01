#!/usr/bin/env python3
"""
Simple wrk-based benchmark comparison between TurboAPI and FastAPI
Uses wrk for accurate performance measurement
"""

import subprocess
import time
import sys
import os

def check_wrk():
    """Check if wrk is installed."""
    wrk_paths = ["/opt/homebrew/bin/wrk", "/usr/local/bin/wrk", "wrk"]
    for wrk_path in wrk_paths:
        try:
            result = subprocess.run([wrk_path, "--version"], capture_output=True)
            if result.returncode in [0, 1]:
                return wrk_path
        except FileNotFoundError:
            continue
    return None

def start_turboapi():
    """Start TurboAPI server on port 8080."""
    print("🚀 Starting TurboAPI on port 8080...")
    process = subprocess.Popen([
        sys.executable, "tests/test.py"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    
    # Verify it's running
    import requests
    try:
        response = requests.get("http://127.0.0.1:8080/", timeout=5)
        if response.status_code == 200:
            print("✅ TurboAPI ready")
            return process
    except:
        pass
    
    print("❌ TurboAPI failed to start")
    process.terminate()
    return None

def start_fastapi():
    """Start FastAPI server on port 8081."""
    print("🚀 Starting FastAPI on port 8081...")
    process = subprocess.Popen([
        sys.executable, "tests/fastapi_equivalent.py"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    
    # Verify it's running
    import requests
    try:
        response = requests.get("http://127.0.0.1:8081/", timeout=5)
        if response.status_code == 200:
            print("✅ FastAPI ready")
            return process
    except:
        pass
    
    print("❌ FastAPI failed to start")
    process.terminate()
    return None

def run_wrk(url, threads=4, connections=100, duration=20, wrk_path="wrk"):
    """Run wrk benchmark and return parsed results."""
    print(f"\n🔥 wrk -t{threads} -c{connections} -d{duration}s {url}")
    
    cmd = [wrk_path, "-t", str(threads), "-c", str(connections), 
           "-d", f"{duration}s", "--latency", url]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stdout
    
    # Parse output
    metrics = {}
    for line in output.split('\n'):
        if 'Requests/sec:' in line:
            metrics['rps'] = float(line.split()[1])
        elif 'Latency' in line and 'avg' not in line:
            parts = line.split()
            if len(parts) >= 4:
                metrics['latency_avg'] = parts[1]
                metrics['latency_stdev'] = parts[2]
                metrics['latency_max'] = parts[3]
        elif 'requests in' in line:
            parts = line.split()
            metrics['total_requests'] = int(parts[0])
            metrics['duration'] = parts[2]
    
    return metrics, output

def kill_port(port):
    """Kill process on port."""
    try:
        subprocess.run(f"lsof -ti:{port} | xargs kill -9 2>/dev/null", 
                      shell=True, capture_output=True)
        time.sleep(1)
    except:
        pass

def generate_visualization(results):
    """Generate a beautiful PNG visualization of benchmark results."""
    try:
        import matplotlib.pyplot as plt
        import numpy as np
        
        # Prepare data
        configs = list(results['turboapi'].keys())
        endpoints = ['Root', 'Simple', 'JSON']
        
        fig, axes = plt.subplots(1, 3, figsize=(18, 6))
        fig.suptitle('TurboAPI vs FastAPI Performance Comparison', 
                     fontsize=16, fontweight='bold')
        
        x = np.arange(len(configs))
        width = 0.35
        
        colors_turbo = '#FF6B35'  # Orange for TurboAPI
        colors_fast = '#4ECDC4'   # Teal for FastAPI
        
        for idx, endpoint in enumerate(endpoints):
            ax = axes[idx]
            
            turbo_rps = [results['turboapi'][config][endpoint].get('rps', 0) 
                        for config in configs]
            fast_rps = [results['fastapi'][config][endpoint].get('rps', 0) 
                       for config in configs]
            
            bars1 = ax.bar(x - width/2, turbo_rps, width, label='TurboAPI',
                          color=colors_turbo, alpha=0.8)
            bars2 = ax.bar(x + width/2, fast_rps, width, label='FastAPI',
                          color=colors_fast, alpha=0.8)
            
            # Add value labels on bars
            for bars in [bars1, bars2]:
                for bar in bars:
                    height = bar.get_height()
                    ax.text(bar.get_x() + bar.get_width()/2., height,
                           f'{int(height):,}',
                           ha='center', va='bottom', fontsize=9)
            
            # Add speedup annotations
            for i, (t, f) in enumerate(zip(turbo_rps, fast_rps)):
                if f > 0:
                    speedup = t / f
                    ax.text(i, max(t, f) * 1.15, f'{speedup:.1f}x',
                           ha='center', va='bottom', fontsize=11, 
                           fontweight='bold', color='#2C3E50')
            
            ax.set_xlabel('Load Configuration', fontweight='bold')
            ax.set_ylabel('Requests/second', fontweight='bold')
            ax.set_title(f'{endpoint} Endpoint', fontweight='bold')
            ax.set_xticks(x)
            ax.set_xticklabels(configs)
            ax.legend()
            ax.grid(axis='y', alpha=0.3, linestyle='--')
            
            # Format y-axis with comma separator
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x):,}'))
        
        plt.tight_layout()
        
        # Save to file
        filename = 'benchmark_comparison.png'
        plt.savefig(filename, dpi=300, bbox_inches='tight')
        print(f"\n🖼️  Visualization saved to: {filename}")
        
        plt.close()
        
    except ImportError:
        print("\n⚠️  matplotlib not available - skipping visualization")
        print("💡 Install with: pip install matplotlib")

def main():
    print("🥊 TurboAPI vs FastAPI Benchmark (wrk)")
    print("=" * 60)
    
    # Check for wrk
    wrk_path = check_wrk()
    if not wrk_path:
        print("❌ wrk not found! Install with: brew install wrk")
        return
    
    print(f"✅ Found wrk at: {wrk_path}\n")
    
    # Clean up ports
    kill_port(8080)
    kill_port(8081)
    
    # Test configurations
    configs = [
        {"name": "Light Load", "threads": 2, "connections": 50, "duration": 20},
        {"name": "Medium Load", "threads": 4, "connections": 200, "duration": 20},
        {"name": "Heavy Load", "threads": 8, "connections": 500, "duration": 20},
    ]
    
    endpoints = [
        ("/", "Root"),
        ("/benchmark/simple", "Simple"),
        ("/benchmark/json", "JSON"),
    ]
    
    results = {}
    
    # Benchmark TurboAPI
    print("\n" + "🚀 TURBOAPI BENCHMARKS ".center(60, "="))
    turbo_proc = start_turboapi()
    if not turbo_proc:
        print("❌ Cannot proceed without TurboAPI")
        return
    
    results['turboapi'] = {}
    for config in configs:
        print(f"\n📊 {config['name']}")
        results['turboapi'][config['name']] = {}
        
        for endpoint, name in endpoints:
            url = f"http://127.0.0.1:8080{endpoint}"
            metrics, _ = run_wrk(url, config['threads'], config['connections'], 
                                config['duration'], wrk_path)
            results['turboapi'][config['name']][name] = metrics
            
            if 'rps' in metrics:
                print(f"  {name}: {metrics['rps']:,.0f} req/s, "
                      f"latency {metrics.get('latency_avg', 'N/A')}")
    
    turbo_proc.terminate()
    time.sleep(2)
    
    # Benchmark FastAPI
    print("\n" + "⚡ FASTAPI BENCHMARKS ".center(60, "="))
    fastapi_proc = start_fastapi()
    if not fastapi_proc:
        print("❌ Cannot proceed without FastAPI")
        kill_port(8080)
        return
    
    results['fastapi'] = {}
    for config in configs:
        print(f"\n📊 {config['name']}")
        results['fastapi'][config['name']] = {}
        
        for endpoint, name in endpoints:
            url = f"http://127.0.0.1:8081{endpoint}"
            metrics, _ = run_wrk(url, config['threads'], config['connections'], 
                                config['duration'], wrk_path)
            results['fastapi'][config['name']][name] = metrics
            
            if 'rps' in metrics:
                print(f"  {name}: {metrics['rps']:,.0f} req/s, "
                      f"latency {metrics.get('latency_avg', 'N/A')}")
    
    fastapi_proc.terminate()
    
    # Comparison
    print("\n" + "📊 PERFORMANCE COMPARISON ".center(60, "="))
    for config in configs:
        print(f"\n🎯 {config['name']}")
        for endpoint, name in endpoints:
            turbo = results['turboapi'][config['name']].get(name, {})
            fast = results['fastapi'][config['name']].get(name, {})
            
            if 'rps' in turbo and 'rps' in fast:
                improvement = turbo['rps'] / fast['rps']
                print(f"  {name}:")
                print(f"    TurboAPI: {turbo['rps']:>10,.0f} req/s")
                print(f"    FastAPI:  {fast['rps']:>10,.0f} req/s")
                print(f"    Speedup:  {improvement:>10.1f}x")
    
    # Generate visualization
    generate_visualization(results)
    
    # Cleanup
    kill_port(8080)
    kill_port(8081)
    
    print("\n✅ Benchmark complete!")

if __name__ == "__main__":
    main()
