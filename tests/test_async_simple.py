#!/usr/bin/env python3
"""
Simple Async Handler Test
Verifies that async handlers are awaited (no coroutine objects returned)

This is a MINIMAL test to confirm the async bug is fixed.
Full async support with query params/headers requires Rust updates.
"""

import time
import threading
import requests
from turboapi import TurboAPI


def test_async_basic():
    """Test that basic async handlers work without parameters"""
    print("\n" + "="*70)
    print("TEST: Basic Async Handler (No Parameters)")
    print("="*70)
    
    app = TurboAPI(title="Async Basic Test")
    
    @app.get("/sync")
    def sync_handler():
        return {"type": "sync", "message": "I am sync"}
    
    @app.get("/async")
    async def async_handler():
        import asyncio
        await asyncio.sleep(0.001)
        return {"type": "async", "message": "I am async"}
    
    def start_server():
        app.run(host="127.0.0.1", port=9800)
    
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)
    
    # Test sync handler
    response = requests.get("http://127.0.0.1:9800/sync")
    print(f"\nGET /sync: {response.status_code}")
    print(f"Response: {response.text}")
    
    assert response.status_code == 200
    assert "coroutine" not in response.text.lower()
    result = response.json()
    assert result["type"] == "sync"
    print("✅ PASSED: Sync handler works")
    
    # Test async handler
    response = requests.get("http://127.0.0.1:9800/async")
    print(f"\nGET /async: {response.status_code}")
    print(f"Response: {response.text}")
    
    # CRITICAL: Should NOT contain "coroutine object"
    if "coroutine" in response.text.lower():
        print(f"❌ FAILED: Async handler returned coroutine object!")
        print(f"   Response: {response.text}")
        return False
    
    assert response.status_code == 200
    
    # Handle both response formats (direct or wrapped in "content")
    result = response.json()
    if isinstance(result, dict) and "content" in result:
        result = result["content"]
    
    assert result["type"] == "async"
    assert result["message"] == "I am async"
    print("✅ PASSED: Async handler properly awaited!")
    
    print("\n✅ ASYNC BASIC TEST PASSED!")
    print("\n🎉 Async handlers are being awaited correctly!")
    print("   No more coroutine objects returned!")
    return True


if __name__ == "__main__":
    import sys
    try:
        success = test_async_basic()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
