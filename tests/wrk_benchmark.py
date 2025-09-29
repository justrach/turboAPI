#!/usr/bin/env python3
"""
Benchmark comparison between TurboAPI and FastAPI using wrk
Enhanced with JSON output and beautiful visualizations
"""

import subprocess
import time
import signal
import os
import sys
import json
from pathlib import Path
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns
import pandas as pd
import numpy as np

def check_wrk():
    """Check if wrk is installed."""
    try:
        # Try different possible paths for wrk
        wrk_paths = ["/opt/homebrew/bin/wrk", "/usr/local/bin/wrk", "wrk"]
        for wrk_path in wrk_paths:
            try:
                result = subprocess.run([wrk_path, "--version"], capture_output=True)
                output = result.stdout.decode() + result.stderr.decode()
                if result.returncode in [0, 1] and "wrk" in output:  # wrk --version returns 1
                    return wrk_path
            except FileNotFoundError:
                continue
        return None
    except Exception:
        return None

def start_server(script_path, port, server_name):
    """Start a server and return the process."""
    print(f"🚀 Starting {server_name} on port {port}...")
    
    if "fastapi" in script_path:
        # FastAPI with uvicorn
        process = subprocess.Popen([
            sys.executable, script_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        # TurboAPI with free-threading Python - disable rate limiting for benchmarking
        env = os.environ.copy()
        env["PYTHONPATH"] = "/Users/rachpradhan/rusty/turboAPI/python"
        env["TURBO_DISABLE_RATE_LIMITING"] = "1"  # Environment flag
        process = subprocess.Popen([
            "/Users/rachpradhan/rusty/turboAPI/turbo-freethreaded/bin/python", script_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    
    # Wait for server to start
    time.sleep(3)
    
    # Test if server is responding
    try:
        import requests
        response = requests.get(f"http://127.0.0.1:{port}/", timeout=5)
        if response.status_code == 200:
            print(f"✅ {server_name} started successfully")
            return process
        else:
            print(f"❌ {server_name} not responding properly")
            process.terminate()
            return None
    except Exception as e:
        print(f"❌ {server_name} failed to start: {e}")
        process.terminate()
        return None

def run_wrk_benchmark(url, duration=30, connections=100, threads=4, wrk_path="wrk"):
    """Run wrk benchmark and parse results."""
    print(f"🔥 Running wrk benchmark: {connections} connections, {threads} threads, {duration}s")
    
    cmd = [
        wrk_path,
        "-t", str(threads),
        "-c", str(connections), 
        "-d", f"{duration}s",
        "--latency",
        url
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 10)
        return parse_wrk_output(result.stdout)
    except subprocess.TimeoutExpired:
        print("❌ Benchmark timed out")
        return None
    except Exception as e:
        print(f"❌ Benchmark failed: {e}")
        return None

def parse_wrk_output(output):
    """Parse wrk output to extract key metrics."""
    lines = output.split('\n')
    metrics = {}
    
    for line in lines:
        if "Requests/sec:" in line:
            metrics["rps"] = float(line.split()[-1])
        elif "Transfer/sec:" in line:
            metrics["transfer_rate"] = line.split()[-1]
        elif "Latency" in line and "avg" in line:
            # Parse latency line: "Latency     1.23ms    2.34ms   45.67ms   89.01%"
            parts = line.split()
            if len(parts) >= 4:
                metrics["latency_avg"] = parts[1]
                metrics["latency_stdev"] = parts[2] 
                metrics["latency_max"] = parts[3]
        elif "50%" in line:
            # Latency distribution
            parts = line.split()
            metrics["latency_p50"] = parts[1]
        elif "90%" in line:
            parts = line.split()
            metrics["latency_p90"] = parts[1]
        elif "99%" in line:
            parts = line.split()
            metrics["latency_p99"] = parts[1]
    
    return metrics

def kill_process_on_port(port):
    """Kill any process using the specified port."""
    try:
        subprocess.run([
            "lsof", "-ti", f":{port}"
        ], capture_output=True, check=True)
        subprocess.run([
            "sh", "-c", f"lsof -ti:{port} | xargs kill -9 2>/dev/null || true"
        ], capture_output=True)
        time.sleep(1)
    except:
        pass

def save_results_to_json(results, filename=None):
    """Save benchmark results to JSON file with timestamp."""
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"turbo_vs_fastapi_benchmark_{timestamp}.json"
    
    # Add metadata
    output_data = {
        "timestamp": datetime.now().isoformat(),
        "benchmark_type": "TurboAPI vs FastAPI Performance Comparison",
        "python_version": sys.version,
        "platform": dict(zip(['sysname', 'nodename', 'release', 'version', 'machine'], os.uname())) if hasattr(os, 'uname') else "unknown",
        "results": results
    }
    
    filepath = Path(filename)
    with open(filepath, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"💾 Results saved to: {filepath.absolute()}")
    return filepath

def create_performance_graphs(results, output_dir="benchmark_graphs"):
    """Create beautiful performance comparison graphs."""
    try:
        # Create output directory
        Path(output_dir).mkdir(exist_ok=True)
        
        # Set up the plotting style
        plt.style.use('seaborn-v0_8-darkgrid')
        sns.set_palette("husl")
        
        # Extract data for plotting
        benchmarks = ["Light Load", "Medium Load", "Heavy Load"]
        turbo_rps = []
        fastapi_rps = []
        turbo_latency = []
        fastapi_latency = []
        
        for benchmark in benchmarks:
            if benchmark in results.get("TurboAPI", {}):
                turbo_rps.append(results["TurboAPI"][benchmark].get("rps", 0))
                # Convert latency to float (remove 'ms' and convert)
                lat_str = results["TurboAPI"][benchmark].get("latency_p99", "0ms")
                turbo_latency.append(float(lat_str.replace('ms', '')) if 'ms' in lat_str else 0)
            else:
                turbo_rps.append(0)
                turbo_latency.append(0)
                
            if benchmark in results.get("FastAPI", {}):
                fastapi_rps.append(results["FastAPI"][benchmark].get("rps", 0))
                lat_str = results["FastAPI"][benchmark].get("latency_p99", "0ms")
                fastapi_latency.append(float(lat_str.replace('ms', '')) if 'ms' in lat_str else 0)
            else:
                fastapi_rps.append(0)
                fastapi_latency.append(0)
        
        # Create figure with subplots
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle('🚀 TurboAPI vs FastAPI Performance Comparison', fontsize=20, fontweight='bold')
        
        # 1. RPS Comparison Bar Chart
        x = np.arange(len(benchmarks))
        width = 0.35
        
        bars1 = ax1.bar(x - width/2, turbo_rps, width, label='TurboAPI', color='#FF6B6B', alpha=0.8)
        bars2 = ax1.bar(x + width/2, fastapi_rps, width, label='FastAPI', color='#4ECDC4', alpha=0.8)
        
        ax1.set_xlabel('Load Test', fontweight='bold')
        ax1.set_ylabel('Requests per Second (RPS)', fontweight='bold')
        ax1.set_title('🔥 Throughput Comparison', fontsize=14, fontweight='bold')
        ax1.set_xticks(x)
        ax1.set_xticklabels(benchmarks)
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # Add value labels on bars
        for bar in bars1:
            height = bar.get_height()
            ax1.annotate(f'{height:.0f}',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3),
                        textcoords="offset points",
                        ha='center', va='bottom', fontweight='bold')
        
        for bar in bars2:
            height = bar.get_height()
            ax1.annotate(f'{height:.0f}',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3),
                        textcoords="offset points",
                        ha='center', va='bottom', fontweight='bold')
        
        # 2. Performance Improvement Chart
        improvements = []
        for i in range(len(benchmarks)):
            if fastapi_rps[i] > 0:
                improvement = ((turbo_rps[i] - fastapi_rps[i]) / fastapi_rps[i]) * 100
                improvements.append(improvement)
            else:
                improvements.append(0)
        
        colors = ['#FF6B6B' if imp > 0 else '#FFA07A' for imp in improvements]
        bars = ax2.bar(benchmarks, improvements, color=colors, alpha=0.8)
        ax2.set_xlabel('Load Test', fontweight='bold')
        ax2.set_ylabel('Performance Improvement (%)', fontweight='bold')
        ax2.set_title('📈 TurboAPI Performance Advantage', fontsize=14, fontweight='bold')
        ax2.grid(True, alpha=0.3)
        
        # Add value labels
        for bar, imp in zip(bars, improvements):
            height = bar.get_height()
            ax2.annotate(f'{imp:.1f}%',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3),
                        textcoords="offset points",
                        ha='center', va='bottom', fontweight='bold')
        
        # 3. Latency Comparison
        bars3 = ax3.bar(x - width/2, turbo_latency, width, label='TurboAPI', color='#FF6B6B', alpha=0.8)
        bars4 = ax3.bar(x + width/2, fastapi_latency, width, label='FastAPI', color='#4ECDC4', alpha=0.8)
        
        ax3.set_xlabel('Load Test', fontweight='bold')
        ax3.set_ylabel('P99 Latency (ms)', fontweight='bold')
        ax3.set_title('⚡ Latency Comparison (Lower is Better)', fontsize=14, fontweight='bold')
        ax3.set_xticks(x)
        ax3.set_xticklabels(benchmarks)
        ax3.legend()
        ax3.grid(True, alpha=0.3)
        
        # Add value labels
        for bar in bars3:
            height = bar.get_height()
            ax3.annotate(f'{height:.2f}ms',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3),
                        textcoords="offset points",
                        ha='center', va='bottom', fontweight='bold')
        
        for bar in bars4:
            height = bar.get_height()
            ax3.annotate(f'{height:.2f}ms',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3),
                        textcoords="offset points",
                        ha='center', va='bottom', fontweight='bold')
        
        # 4. Performance Summary Radar Chart
        categories = ['Light\nLoad', 'Medium\nLoad', 'Heavy\nLoad']
        
        # Normalize RPS values for radar chart (0-1 scale)
        max_rps = max(max(turbo_rps), max(fastapi_rps))
        turbo_normalized = [rps/max_rps for rps in turbo_rps]
        fastapi_normalized = [rps/max_rps for rps in fastapi_rps]
        
        # Create radar chart
        angles = np.linspace(0, 2*np.pi, len(categories), endpoint=False).tolist()
        angles += angles[:1]  # Complete the circle
        
        turbo_normalized += turbo_normalized[:1]
        fastapi_normalized += fastapi_normalized[:1]
        
        ax4.plot(angles, turbo_normalized, 'o-', linewidth=2, label='TurboAPI', color='#FF6B6B')
        ax4.fill(angles, turbo_normalized, alpha=0.25, color='#FF6B6B')
        ax4.plot(angles, fastapi_normalized, 'o-', linewidth=2, label='FastAPI', color='#4ECDC4')
        ax4.fill(angles, fastapi_normalized, alpha=0.25, color='#4ECDC4')
        
        ax4.set_xticks(angles[:-1])
        ax4.set_xticklabels(categories)
        ax4.set_ylim(0, 1)
        ax4.set_title('🎯 Performance Profile', fontsize=14, fontweight='bold')
        ax4.legend()
        ax4.grid(True)
        
        plt.tight_layout()
        
        # Save the plot
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        graph_file = Path(output_dir) / f"turbo_vs_fastapi_performance_{timestamp}.png"
        plt.savefig(graph_file, dpi=300, bbox_inches='tight', facecolor='white')
        print(f"📊 Performance graphs saved to: {graph_file.absolute()}")
        
        # Show the plot
        plt.show()
        
        return graph_file
        
    except ImportError as e:
        print(f"⚠️  Visualization libraries not available: {e}")
        print("💡 Install with: pip install matplotlib seaborn pandas")
        return None
    except Exception as e:
        print(f"❌ Error creating graphs: {e}")
        return None

def main():
    print("🥊 TurboAPI vs FastAPI Benchmark Comparison")
    print("=" * 60)
    
    # Check prerequisites
    wrk_path = check_wrk()
    if not wrk_path:
        print("❌ wrk not found. Install with: brew install wrk")
        return
    
    # Clean up any existing processes
    kill_process_on_port(8080)
    kill_process_on_port(8081)
    
    # Benchmark configurations
    benchmarks = [
        {"name": "Light Load", "connections": 50, "threads": 4, "duration": 20},
        {"name": "Medium Load", "connections": 100, "threads": 8, "duration": 20},
        {"name": "Heavy Load", "connections": 200, "threads": 12, "duration": 20},
    ]
    
    results = {}
    
    # Test TurboAPI
    print("\n🚀 TURBOAPI BENCHMARKS")
    print("-" * 40)
    
    turbo_process = start_server("/Users/rachpradhan/rusty/turboAPI/tests/test.py", 8080, "TurboAPI")
    if turbo_process:
        results["TurboAPI"] = {}
        
        for benchmark in benchmarks:
            print(f"\n📊 {benchmark['name']} Test:")
            metrics = run_wrk_benchmark(
                "http://127.0.0.1:8080/search?q=benchmark&limit=10",
                duration=benchmark["duration"],
                connections=benchmark["connections"], 
                threads=benchmark["threads"],
                wrk_path=wrk_path
            )
            
            if metrics:
                results["TurboAPI"][benchmark["name"]] = metrics
                print(f"   RPS: {metrics.get('rps', 0):.0f}")
                print(f"   Avg Latency: {metrics.get('latency_avg', 'N/A')}")
                print(f"   P99 Latency: {metrics.get('latency_p99', 'N/A')}")
        
        turbo_process.terminate()
        time.sleep(2)
    
    # Test FastAPI
    print("\n⚡ FASTAPI BENCHMARKS")
    print("-" * 40)
    
    fastapi_process = start_server("/Users/rachpradhan/rusty/turboAPI/tests/fastapi_equivalent.py", 8081, "FastAPI")
    if fastapi_process:
        results["FastAPI"] = {}
        
        for benchmark in benchmarks:
            print(f"\n📊 {benchmark['name']} Test:")
            metrics = run_wrk_benchmark(
                "http://127.0.0.1:8081/search?q=benchmark&limit=10",
                duration=benchmark["duration"],
                connections=benchmark["connections"],
                threads=benchmark["threads"],
                wrk_path=wrk_path
            )
            
            if metrics:
                results["FastAPI"][benchmark["name"]] = metrics
                print(f"   RPS: {metrics.get('rps', 0):.0f}")
                print(f"   Avg Latency: {metrics.get('latency_avg', 'N/A')}")
                print(f"   P99 Latency: {metrics.get('latency_p99', 'N/A')}")
        
        fastapi_process.terminate()
        time.sleep(2)
    
    # Compare results
    print("\n🏆 BENCHMARK COMPARISON RESULTS")
    print("=" * 60)
    
    if "TurboAPI" in results and "FastAPI" in results:
        for benchmark_name in ["Light Load", "Medium Load", "Heavy Load"]:
            if benchmark_name in results["TurboAPI"] and benchmark_name in results["FastAPI"]:
                turbo_rps = results["TurboAPI"][benchmark_name].get("rps", 0)
                fastapi_rps = results["FastAPI"][benchmark_name].get("rps", 0)
                
                if fastapi_rps > 0:
                    improvement = (turbo_rps / fastapi_rps) * 100
                    print(f"\n📊 {benchmark_name}:")
                    print(f"   TurboAPI:  {turbo_rps:.0f} RPS")
                    print(f"   FastAPI:   {fastapi_rps:.0f} RPS")
                    print(f"   🚀 TurboAPI is {improvement:.1f}% of FastAPI performance")
                    
                    if improvement > 100:
                        print(f"   ✅ TurboAPI is {improvement-100:.1f}% FASTER!")
                    else:
                        print(f"   ⚠️  TurboAPI is {100-improvement:.1f}% slower")
    
    # Clean up
    kill_process_on_port(8080)
    kill_process_on_port(8081)
    
    # Save results to JSON
    json_file = save_results_to_json(results)
    
    # Create performance graphs
    print("\n📊 Creating performance visualizations...")
    graph_file = create_performance_graphs(results)
    
    print(f"\n🎯 Benchmark completed!")
    print(f"📝 Note: TurboAPI is running on Python 3.13+ free-threading")
    print(f"📝 Note: FastAPI is running on standard Python with uvicorn")
    print(f"\n📁 Output files:")
    print(f"   📄 JSON Results: {json_file}")
    if graph_file:
        print(f"   📊 Performance Graphs: {graph_file}")
    
    # Display summary statistics
    if "TurboAPI" in results and "FastAPI" in results:
        print(f"\n🏆 PERFORMANCE SUMMARY:")
        print(f"=" * 40)
        
        total_turbo_rps = sum(results["TurboAPI"][b].get("rps", 0) for b in ["Light Load", "Medium Load", "Heavy Load"] if b in results["TurboAPI"])
        total_fastapi_rps = sum(results["FastAPI"][b].get("rps", 0) for b in ["Light Load", "Medium Load", "Heavy Load"] if b in results["FastAPI"])
        
        if total_fastapi_rps > 0:
            overall_improvement = ((total_turbo_rps - total_fastapi_rps) / total_fastapi_rps) * 100
            print(f"🚀 Overall TurboAPI Performance: {overall_improvement:.1f}% improvement")
            print(f"⚡ Total RPS - TurboAPI: {total_turbo_rps:.0f} | FastAPI: {total_fastapi_rps:.0f}")
            
            # Find best performing scenario
            best_improvement = 0
            best_scenario = ""
            for benchmark_name in ["Light Load", "Medium Load", "Heavy Load"]:
                if benchmark_name in results["TurboAPI"] and benchmark_name in results["FastAPI"]:
                    turbo_rps = results["TurboAPI"][benchmark_name].get("rps", 0)
                    fastapi_rps = results["FastAPI"][benchmark_name].get("rps", 0)
                    if fastapi_rps > 0:
                        improvement = ((turbo_rps - fastapi_rps) / fastapi_rps) * 100
                        if improvement > best_improvement:
                            best_improvement = improvement
                            best_scenario = benchmark_name
            
            if best_scenario:
                print(f"🎯 Best Performance: {best_scenario} with {best_improvement:.1f}% improvement")

if __name__ == "__main__":
    main()
