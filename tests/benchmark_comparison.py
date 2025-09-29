#!/usr/bin/env python3
"""
Comprehensive benchmark comparison between TurboAPI and FastAPI.
Integrates adaptive rate testing from adaptive_rate_test.py with side-by-side comparison.
"""

import time
import subprocess
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import statistics
import json

def wait_for_server(url, max_wait=30, check_interval=0.5):
    """Wait for server to be ready"""
    start_time = time.time()
    while time.time() - start_time < max_wait:
        try:
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            time.sleep(check_interval)
    return False

def measure_response_times(url, num_requests=100, concurrent=False, max_workers=10):
    """Measure response times for a given endpoint"""
    response_times = []
    errors = 0
    
    def make_request():
        try:
            start = time.time()
            response = requests.get(url, timeout=5)
            end = time.time()
            
            if response.status_code == 200:
                return end - start
            else:
                return None
        except:
            return None
    
    if concurrent:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(make_request) for _ in range(num_requests)]
            
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    response_times.append(result)
                else:
                    errors += 1
    else:
        for _ in range(num_requests):
            result = make_request()
            if result is not None:
                response_times.append(result)
            else:
                errors += 1
    
    if not response_times:
        return None
    
    return {
        'count': len(response_times),
        'errors': errors,
        'mean': statistics.mean(response_times),
        'median': statistics.median(response_times),
        'min': min(response_times),
        'max': max(response_times),
        'p95': sorted(response_times)[int(0.95 * len(response_times))],
        'p99': sorted(response_times)[int(0.99 * len(response_times))],
    }

def adaptive_rate_test_comparison(base_url, endpoint="/benchmark/simple", framework_name="API"):
    """Adaptive rate testing optimized for comparison"""
    print(f"🧪 {framework_name} Adaptive Rate Test: {endpoint}")
    
    # Progressive rate testing - find the breaking point
    test_rates = [100, 500, 1000, 2000, 5000, 10000, 20000, 50000]
    
    max_sustainable_rate = 0
    
    for target_rps in test_rates:
        interval = 1.0 / target_rps
        total_requests = min(200, target_rps // 10)  # Adaptive test size
        
        print(f"  Testing {target_rps:,} RPS...", end=" ")
        
        success_count = 0
        start_time = time.time()
        
        for _ in range(total_requests):
            try:
                response = requests.get(f"{base_url}{endpoint}", timeout=1)
                if response.status_code == 200:
                    success_count += 1
                time.sleep(interval)
            except:
                pass
        
        duration = time.time() - start_time
        actual_rps = success_count / duration if duration > 0 else 0
        success_rate = success_count / total_requests * 100
        
        if success_rate >= 90:
            max_sustainable_rate = target_rps
            print(f"✅ {actual_rps:.0f} RPS achieved ({success_rate:.1f}% success)")
        else:
            print(f"❌ {actual_rps:.0f} RPS ({success_rate:.1f}% success) - LIMIT REACHED")
            break
    
    return max_sustainable_rate

def run_benchmark_suite(framework, port, script_name):
    """Run a complete benchmark suite for a framework"""
    
    print(f"\n🚀 Starting {framework} server...")
    
    # Start the server
    if framework == "TurboAPI":
        process = subprocess.Popen(['python3', 'tests/test.py'], 
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:  # FastAPI
        process = subprocess.Popen(['python3', 'tests/fastapi_equivalent.py'], 
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    # Wait for server to be ready
    base_url = f"http://127.0.0.1:{port}"
    if not wait_for_server(base_url):
        print(f"❌ {framework} server failed to start!")
        process.terminate()
        return None
    
    print(f"✅ {framework} server ready at {base_url}")
    
    # Test endpoints
    endpoints = [
        "/",
        "/benchmark/simple", 
        "/benchmark/medium",
        "/benchmark/json"
    ]
    
    results = {
        'framework': framework,
        'port': port,
        'endpoints': {}
    }
    
    for endpoint in endpoints:
        print(f"\n📊 Testing {framework} endpoint: {endpoint}")
        
        # Response time measurements
        url = f"{base_url}{endpoint}"
        
        # Sequential requests
        sequential_stats = measure_response_times(url, 50, concurrent=False)
        
        # Concurrent requests
        concurrent_stats = measure_response_times(url, 50, concurrent=True, max_workers=10)
        
        # Adaptive rate test
        max_rate = adaptive_rate_test_comparison(base_url, endpoint, framework)
        
        results['endpoints'][endpoint] = {
            'sequential': sequential_stats,
            'concurrent': concurrent_stats,
            'max_sustainable_rps': max_rate
        }
        
        if sequential_stats:
            print(f"  Sequential - Mean: {sequential_stats['mean']*1000:.2f}ms, P95: {sequential_stats['p95']*1000:.2f}ms")
        if concurrent_stats:
            print(f"  Concurrent - Mean: {concurrent_stats['mean']*1000:.2f}ms, P95: {concurrent_stats['p95']*1000:.2f}ms")
        print(f"  Max Sustainable Rate: {max_rate:,} RPS")
    
    # Cleanup
    process.terminate()
    
    return results

def compare_frameworks():
    """Run comprehensive comparison between TurboAPI and FastAPI"""
    
    print("🏁 TurboAPI vs FastAPI Benchmark Comparison")
    print("=" * 50)
    
    # Run TurboAPI benchmark
    turbo_results = run_benchmark_suite("TurboAPI", 8080, "tests/test.py")
    
    # Wait between tests
    time.sleep(2)
    
    # Run FastAPI benchmark  
    fastapi_results = run_benchmark_suite("FastAPI", 8081, "tests/fastapi_equivalent.py")
    
    if not turbo_results or not fastapi_results:
        print("❌ Failed to run complete benchmark comparison")
        return
    
    # Generate comparison report
    print("\n" + "=" * 60)
    print("📊 BENCHMARK COMPARISON REPORT")
    print("=" * 60)
    
    for endpoint in turbo_results['endpoints'].keys():
        print(f"\n🎯 Endpoint: {endpoint}")
        print("-" * 40)
        
        turbo_ep = turbo_results['endpoints'][endpoint]
        fastapi_ep = fastapi_results['endpoints'][endpoint]
        
        # Sequential performance
        if turbo_ep['sequential'] and fastapi_ep['sequential']:
            turbo_seq = turbo_ep['sequential']['mean'] * 1000
            fastapi_seq = fastapi_ep['sequential']['mean'] * 1000
            improvement = fastapi_seq / turbo_seq if turbo_seq > 0 else 0
            
            print(f"Sequential Response Time:")
            print(f"  TurboAPI: {turbo_seq:.2f}ms")
            print(f"  FastAPI:  {fastapi_seq:.2f}ms")
            print(f"  TurboAPI is {improvement:.1f}x faster" if improvement > 1 else f"  FastAPI is {1/improvement:.1f}x faster")
        
        # Concurrent performance  
        if turbo_ep['concurrent'] and fastapi_ep['concurrent']:
            turbo_conc = turbo_ep['concurrent']['mean'] * 1000
            fastapi_conc = fastapi_ep['concurrent']['mean'] * 1000
            improvement = fastapi_conc / turbo_conc if turbo_conc > 0 else 0
            
            print(f"Concurrent Response Time:")
            print(f"  TurboAPI: {turbo_conc:.2f}ms")
            print(f"  FastAPI:  {fastapi_conc:.2f}ms")
            print(f"  TurboAPI is {improvement:.1f}x faster" if improvement > 1 else f"  FastAPI is {1/improvement:.1f}x faster")
        
        # Throughput comparison
        turbo_rps = turbo_ep['max_sustainable_rps']
        fastapi_rps = fastapi_ep['max_sustainable_rps']
        
        print(f"Maximum Sustainable RPS:")
        print(f"  TurboAPI: {turbo_rps:,} RPS")
        print(f"  FastAPI:  {fastapi_rps:,} RPS")
        
        if turbo_rps > 0 and fastapi_rps > 0:
            throughput_improvement = turbo_rps / fastapi_rps
            print(f"  TurboAPI delivers {throughput_improvement:.1f}x higher throughput")
        elif turbo_rps > fastapi_rps:
            print(f"  TurboAPI significantly outperforms FastAPI")
    
    # Overall summary
    print(f"\n🏆 OVERALL PERFORMANCE SUMMARY")
    print("=" * 40)
    
    # Calculate average improvements
    seq_improvements = []
    conc_improvements = []
    rps_improvements = []
    
    for endpoint in turbo_results['endpoints'].keys():
        turbo_ep = turbo_results['endpoints'][endpoint]
        fastapi_ep = fastapi_results['endpoints'][endpoint]
        
        if turbo_ep['sequential'] and fastapi_ep['sequential']:
            seq_improvements.append(fastapi_ep['sequential']['mean'] / turbo_ep['sequential']['mean'])
        
        if turbo_ep['concurrent'] and fastapi_ep['concurrent']:
            conc_improvements.append(fastapi_ep['concurrent']['mean'] / turbo_ep['concurrent']['mean'])
        
        if turbo_ep['max_sustainable_rps'] > 0 and fastapi_ep['max_sustainable_rps'] > 0:
            rps_improvements.append(turbo_ep['max_sustainable_rps'] / fastapi_ep['max_sustainable_rps'])
    
    if seq_improvements:
        avg_seq = statistics.mean(seq_improvements)
        print(f"Average Sequential Latency Improvement: {avg_seq:.1f}x")
    
    if conc_improvements:  
        avg_conc = statistics.mean(conc_improvements)
        print(f"Average Concurrent Latency Improvement: {avg_conc:.1f}x")
    
    if rps_improvements:
        avg_rps = statistics.mean(rps_improvements) 
        print(f"Average Throughput Improvement: {avg_rps:.1f}x")
    
    print(f"\n✅ Benchmark comparison completed!")
    
    # Save results to file
    with open('benchmark_results.json', 'w') as f:
        json.dump({
            'turboapi': turbo_results,
            'fastapi': fastapi_results,
            'timestamp': time.time()
        }, f, indent=2)
    
    print(f"📄 Detailed results saved to: benchmark_results.json")

if __name__ == "__main__":
    compare_frameworks()
