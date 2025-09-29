#!/usr/bin/env python3
"""
Quick test to verify TurboAPI is working without rate limiting issues
"""

import time
import requests
import threading
from turboapi import TurboAPI

app = TurboAPI(title="Quick Test", version="1.0.0")

# Disable rate limiting for testing
app.configure_rate_limiting(enabled=False)

@app.get("/")
def read_root():
    return {"message": "Hello from TurboAPI!", "status": "working"}

@app.get("/test")
def test_endpoint():
    return {"test": "success", "timestamp": time.time()}

def run_server():
    """Run server in a separate thread"""
    app.run(host="127.0.0.1", port=8080)

def test_requests():
    """Make test requests to verify no rate limiting"""
    time.sleep(2)  # Give server time to start
    
    try:
        # Make multiple requests quickly
        for i in range(10):
            response = requests.get("http://127.0.0.1:8080/", timeout=5)
            print(f"Request {i+1}: Status {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"  Response: {data}")
            else:
                print(f"  Error: {response.text}")
            time.sleep(0.1)
            
        # Test the /test endpoint
        response = requests.get("http://127.0.0.1:8080/test", timeout=5)
        print(f"Test endpoint: Status {response.status_code}")
        if response.status_code == 200:
            print(f"  Response: {response.json()}")
        else:
            print(f"  Error: {response.text}")
            
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    # Start server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Run tests
    test_requests()
    
    print("✅ Quick test completed!")
