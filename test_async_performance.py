#!/usr/bin/env python3
"""
Quick async performance test using concurrent requests
"""
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from turboapi import TurboAPI
import threading

# Create TurboAPI app
app = TurboAPI()

@app.get("/sync")
def sync_handler():
    return {"type": "sync", "message": "works"}

@app.get("/async")
async def async_handler():
    return {"type": "async", "message": "works"}

def start_server():
    """Start server in background thread"""
    app.run(host="127.0.0.1", port=8001)

def benchmark_endpoint(url, num_requests=1000, concurrency=50):
    """Benchmark an endpoint with concurrent requests"""
    print(f"\n🔬 Benchmarking {url}")
    print(f"   Requests: {num_requests}, Concurrency: {concurrency}")
    
    successful = 0
    failed = 0
    start_time = time.time()
    
    def make_request(_):
        try:
            response = requests.get(url, timeout=5)
            return response.status_code == 200
        except Exception as e:
            return False
    
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(make_request, i) for i in range(num_requests)]
        for future in as_completed(futures):
            if future.result():
                successful += 1
            else:
                failed += 1
    
    elapsed = time.time() - start_time
    rps = num_requests / elapsed
    
    print(f"   ✅ Successful: {successful}")
    print(f"   ❌ Failed: {failed}")
    print(f"   ⏱️  Time: {elapsed:.2f}s")
    print(f"   🚀 RPS: {rps:.0f}")
    
    return rps

if __name__ == "__main__":
    print("🚀 Starting TurboAPI server...")
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(3)  # Wait for server to start
    
    print("\n" + "="*60)
    print("📊 ASYNC PERFORMANCE TEST")
    print("="*60)
    
    # Warm up
    print("\n🔥 Warming up...")
    requests.get("http://127.0.0.1:8001/sync")
    requests.get("http://127.0.0.1:8001/async")
    time.sleep(1)
    
    # Benchmark sync endpoint
    sync_rps = benchmark_endpoint("http://127.0.0.1:8001/sync", num_requests=5000, concurrency=100)
    
    # Benchmark async endpoint
    async_rps = benchmark_endpoint("http://127.0.0.1:8001/async", num_requests=5000, concurrency=100)
    
    # Results
    print("\n" + "="*60)
    print("📈 RESULTS")
    print("="*60)
    print(f"Sync RPS:  {sync_rps:>10,.0f}")
    print(f"Async RPS: {async_rps:>10,.0f}")
    
    if async_rps > sync_rps * 0.8:
        print(f"\n✅ ASYNC PERFORMANCE: EXCELLENT!")
        print(f"   Async is {async_rps/sync_rps:.1f}x relative to sync")
    elif async_rps > sync_rps * 0.5:
        print(f"\n⚠️  ASYNC PERFORMANCE: GOOD")
        print(f"   Async is {async_rps/sync_rps:.1f}x relative to sync")
    else:
        print(f"\n❌ ASYNC PERFORMANCE: NEEDS IMPROVEMENT")
        print(f"   Async is only {async_rps/sync_rps:.1f}x relative to sync")
    
    print("\n" + "="*60)
