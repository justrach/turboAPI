#!/usr/bin/env python3
"""
Test rate limiting configuration for TurboAPI
"""

from turboapi import TurboAPI
import time

# Create TurboAPI app
app = TurboAPI(title="Rate Limiting Test", version="1.0.0")

@app.get("/")
def read_root():
    return {"message": "Hello from TurboAPI!", "timestamp": time.time()}

@app.get("/test")
def test_endpoint():
    return {"test": "success", "rate_limiting": "configured"}

if __name__ == "__main__":
    print("🧪 Testing Rate Limiting Configuration")
    print("=" * 50)
    
    # Test 1: Disable rate limiting (default for benchmarking)
    print("\n1️⃣ Disabling rate limiting (default for benchmarking)")
    app.configure_rate_limiting(enabled=False)
    
    # Test 2: Enable rate limiting with high limit
    print("\n2️⃣ Enabling rate limiting with high limit")
    app.configure_rate_limiting(enabled=True, requests_per_minute=50000)
    
    # Test 3: Enable rate limiting with low limit (for production)
    print("\n3️⃣ Enabling rate limiting with production limit")
    app.configure_rate_limiting(enabled=True, requests_per_minute=1000)
    
    # Test 4: Disable again for benchmarking
    print("\n4️⃣ Disabling rate limiting for benchmarking")
    app.configure_rate_limiting(enabled=False)
    
    print("\n✅ Rate limiting configuration test completed!")
    print("🚀 Starting server with rate limiting disabled...")
    
    # Start server
    app.run(host="127.0.0.1", port=8080)
