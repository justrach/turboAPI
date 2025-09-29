#!/usr/bin/env python3
"""
Test TurboAPI with rate limiting completely disabled
"""

import time
import requests
import threading
from turboapi import TurboAPI

# Create TurboAPI app
app = TurboAPI(title="No Rate Limit Test", version="1.0.0")

# EXPLICITLY disable rate limiting
app.configure_rate_limiting(enabled=False, requests_per_minute=1000000)

@app.get("/")
def read_root():
    return {"message": "Hello from TurboAPI!", "status": "no_rate_limit", "timestamp": time.time()}

def run_server():
    """Run server in a separate thread"""
    app.run(host="127.0.0.1", port=8082)  # Different port to avoid conflicts

def test_many_requests():
    """Make 400-500 requests quickly to stress test no rate limiting"""
    time.sleep(3)  # Give server time to start
    
    print("🧪 STRESS TESTING with 450 rapid requests...")
    success_count = 0
    error_count = 0
    rate_limit_errors = 0
    
    try:
        # Make 450 requests very quickly to stress test
        for i in range(450):
            response = requests.get("http://127.0.0.1:8082/", timeout=2)
            
            if response.status_code == 200:
                success_count += 1
                if i % 50 == 0:  # Print every 50th request
                    data = response.json()
                    print(f"Request {i+1}: Status {response.status_code} ✅ {data.get('status', 'ok')}")
            elif response.status_code == 429:
                rate_limit_errors += 1
                if rate_limit_errors <= 3:  # Only print first few rate limit errors
                    print(f"Request {i+1}: Status 429 ❌ RATE LIMITED: {response.text[:50]}...")
            else:
                error_count += 1
                if error_count <= 3:  # Only print first few other errors
                    print(f"Request {i+1}: Status {response.status_code} ❌ Error: {response.text[:50]}...")
            
            time.sleep(0.01)  # Very short delay between requests (100 req/sec)
            
    except Exception as e:
        print(f"Request failed: {e}")
    
    print(f"\n📊 STRESS TEST Results:")
    print(f"   ✅ Successful requests: {success_count}")
    print(f"   ❌ Rate limit errors: {rate_limit_errors}")
    print(f"   ❌ Other errors: {error_count}")
    print(f"   📈 Success rate: {success_count/450*100:.1f}%")
    
    return rate_limit_errors == 0 and success_count >= 400  # Should get almost all successful

if __name__ == "__main__":
    print("🚀 Testing TurboAPI with Rate Limiting DISABLED")
    print("=" * 50)
    
    # Start server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Run tests
    success = test_many_requests()
    
    if success:
        print("✅ Rate limiting appears to be disabled - getting successful responses!")
    else:
        print("❌ Still getting rate limit errors - fix needed")
    
    print("🏁 Test completed!")
