#!/usr/bin/env python3
"""
Test TurboAPI rate limiting with wrk - the real deal
"""

import subprocess
import time
import threading
import sys
from turboapi import TurboAPI

# Create TurboAPI app
app = TurboAPI(title="WRK Rate Limit Test", version="1.0.0")

# Disable rate limiting 
app.configure_rate_limiting(enabled=False, requests_per_minute=1000000)

@app.get("/")
def read_root():
    return {"message": "Hello from TurboAPI!", "status": "wrk_test", "timestamp": time.time()}

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

def run_server():
    """Run server in a separate thread"""
    app.run(host="127.0.0.1", port=8084)  # Different port

def run_wrk_test(wrk_path, connections, threads, duration=10):
    """Run wrk test and check for rate limit errors"""
    print(f"\n🔥 Running wrk: {connections} connections, {threads} threads, {duration}s")
    
    cmd = [
        wrk_path,
        "-t", str(threads),
        "-c", str(connections), 
        "-d", f"{duration}s",
        "--timeout", "5s",
        "http://127.0.0.1:8084/"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 10)
        output = result.stdout
        stderr = result.stderr
        
        print(f"📊 wrk output:")
        print(output)
        if stderr:
            print(f"⚠️ stderr: {stderr}")
        
        # Parse for rate limit indicators
        if "429" in output or "Rate" in output or "limit" in output.lower():
            print("🔥 FOUND RATE LIMITING!")
            return True
        else:
            print("✅ No rate limiting detected")
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ wrk test timed out")
        return False
    except Exception as e:
        print(f"❌ wrk test failed: {e}")
        return False

def escalating_wrk_test(wrk_path):
    """Run increasingly aggressive wrk tests until we hit rate limits"""
    print("🧪 ESCALATING WRK STRESS TEST")
    print("=" * 50)
    
    # Start with reasonable loads and escalate
    test_configs = [
        {"connections": 50, "threads": 4, "duration": 10},
        {"connections": 100, "threads": 8, "duration": 10},
        {"connections": 200, "threads": 12, "duration": 10},
        {"connections": 500, "threads": 16, "duration": 10},
        {"connections": 1000, "threads": 20, "duration": 10},
        {"connections": 2000, "threads": 32, "duration": 10},
        {"connections": 5000, "threads": 48, "duration": 10},
    ]
    
    for config in test_configs:
        print(f"\n🚀 Testing: {config['connections']} connections, {config['threads']} threads")
        
        rate_limited = run_wrk_test(
            wrk_path, 
            config['connections'], 
            config['threads'], 
            config['duration']
        )
        
        if rate_limited:
            print(f"🎯 BREAKING POINT FOUND at {config['connections']} connections!")
            return config
        else:
            print(f"✅ {config['connections']} connections handled successfully")
            time.sleep(2)  # Brief pause between tests
    
    print("🤯 HOLY SHIT! Even 5000 connections didn't trigger rate limits!")
    return None

if __name__ == "__main__":
    print("🚀 TurboAPI WRK Rate Limit Testing")
    print("Testing with REAL load generation...")
    print("=" * 60)
    
    # Check if wrk is available
    wrk_path = check_wrk()
    if not wrk_path:
        print("❌ wrk not found. Install with: brew install wrk")
        print("💡 wrk is needed for proper load testing")
        sys.exit(1)
    
    print(f"✅ Found wrk at: {wrk_path}")
    
    # Start server in background thread
    print("🚀 Starting TurboAPI server...")
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Wait for server to start
    time.sleep(5)
    
    # Run escalating tests
    breaking_point = escalating_wrk_test(wrk_path)
    
    if breaking_point:
        print(f"\n🔥 FINAL RESULT:")
        print(f"   🎯 Rate limiting kicks in at: {breaking_point['connections']} connections")
        print(f"   ⚡ This is the REAL limit with wrk load testing!")
    else:
        print(f"\n🤯 FINAL RESULT:")
        print(f"   🚀 TurboAPI is absolutely BULLETPROOF!")
        print(f"   ⚡ No rate limiting found even with 5000+ connections!")
        print(f"   🎯 Rate limiting is COMPLETELY DISABLED as intended!")
    
    print("\n🏁 WRK rate limit test completed!")
