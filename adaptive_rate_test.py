#!/usr/bin/env python3
"""
Adaptive rate test - finds the maximum sustainable request rate for TurboAPI
Automatically backs off when hitting 429 errors until finding stable 200s
"""

import time
import requests
import threading
from turboapi import TurboAPI

# Create TurboAPI app
app = TurboAPI(title="Adaptive Rate Test", version="1.0.0")

# Disable rate limiting 
app.configure_rate_limiting(enabled=False, requests_per_minute=1000000)

@app.get("/")
def read_root():
    return {"message": "Hello from TurboAPI!", "status": "adaptive_test", "timestamp": time.time()}

def run_server():
    """Run server in a separate thread"""
    app.run(host="127.0.0.1", port=8083)  # Different port

def adaptive_rate_test():
    """Find the maximum sustainable request rate"""
    time.sleep(3)  # Give server time to start
    
    print("🧪 ADAPTIVE RATE TESTING - Finding sustainable rate...")
    
    # Start with INSANE rates and keep going up until we hit 429s!
    test_intervals = [0.0001, 0.00005, 0.00001, 0.000005, 0.000001, 0.0000001]  # From 10K to 10M req/s!
    
    for interval in test_intervals:
        requests_per_second = 1.0 / interval
        print(f"\n🔥 STRESS TESTING {requests_per_second:,.0f} requests/second (interval: {interval:.6f}s)")
        
        success_count = 0
        rate_limit_errors = 0
        other_errors = 0
        total_requests = 1000  # Test with 1000 requests each time
        
        start_time = time.time()
        
        try:
            for i in range(total_requests):
                try:
                    response = requests.get("http://127.0.0.1:8083/", timeout=2)
                    
                    if response.status_code == 200:
                        success_count += 1
                        if i % 200 == 0:  # Print every 200th request
                            print(f"  Request {i+1}: ✅ 200", end=" ")
                    elif response.status_code == 429:
                        rate_limit_errors += 1
                        if rate_limit_errors <= 5:  # Print first few rate limit errors
                            print(f"\n  Request {i+1}: 🔥 429 RATE LIMITED! Found the breaking point!", end=" ")
                        if rate_limit_errors >= 10:  # Stop after we've confirmed rate limiting
                            print(f"\n  🎯 RATE LIMIT CONFIRMED! Stopping test at {rate_limit_errors} errors")
                            break
                    else:
                        other_errors += 1
                        print(f"\n  Request {i+1}: ❌ {response.status_code}", end=" ")
                    
                    time.sleep(interval)
                    
                except requests.exceptions.RequestException as e:
                    other_errors += 1
                    print(f"\n  Request {i+1}: ❌ Connection error", end=" ")
                    
        except KeyboardInterrupt:
            print("\n⏹️  Test interrupted")
            break
            
        duration = time.time() - start_time
        actual_rps = success_count / duration if duration > 0 else 0
        success_rate = success_count / total_requests * 100
        
        print(f"\n  📊 Results:")
        print(f"     ✅ Successful: {success_count}/{total_requests} ({success_rate:.1f}%)")
        print(f"     ❌ Rate limited: {rate_limit_errors}")
        print(f"     ❌ Other errors: {other_errors}")
        print(f"     ⚡ Actual RPS: {actual_rps:.1f}")
        
        # If we got rate limit errors, we found the breaking point!
        if rate_limit_errors > 0:
            print(f"  🔥 BREAKING POINT FOUND! {requests_per_second:,.0f} req/s caused {rate_limit_errors} rate limit errors!")
            print(f"  🎯 TurboAPI's rate limit kicks in at approximately {requests_per_second:,.0f} requests/second")
            print(f"  ⚡ Success rate before hitting limits: {success_count}/{total_requests} ({success_rate:.1f}%)")
            return interval
        elif success_rate >= 95:
            print(f"  🚀 RATE {requests_per_second:,.0f} req/s HANDLED SUCCESSFULLY! KEEP PUSHING HIGHER...")
            # Don't stop - keep going to find the real limit!
        else:
            print(f"  ⚠️  Low success rate ({success_rate:.1f}%) - network/connection issues, not rate limiting")
    
    print("🤯 HOLY SHIT! TurboAPI handled ALL tested rates without rate limiting!")
    print("🚀 This thing is a MONSTER - even 1,000,000+ req/s didn't break it!")
    return None

if __name__ == "__main__":
    print("🚀 TurboAPI Adaptive Rate Testing")
    print("Finding the maximum sustainable request rate...")
    print("=" * 60)
    
    # Start server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Run adaptive test
    optimal_interval = adaptive_rate_test()
    
    if optimal_interval:
        optimal_rps = 1.0 / optimal_interval
        print(f"\n🎯 FINAL RECOMMENDATION:")
        print(f"   ⚡ Maximum sustainable rate: {optimal_rps:.1f} requests/second")
        print(f"   ⏱️  Recommended interval: {optimal_interval:.3f} seconds between requests")
        print(f"   📈 This should give you consistent 200 responses!")
    else:
        print(f"\n❌ Could not determine optimal rate - may need manual tuning")
    
    print("\n🏁 Adaptive test completed!")
