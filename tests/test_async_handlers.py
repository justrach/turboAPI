#!/usr/bin/env python3
"""
Comprehensive Tests for Async Handler Support
Tests that async def handlers are properly awaited and return correct responses

BUG: TurboAPI v0.4.13 returns coroutine objects instead of awaiting async handlers
FIX: v0.4.15 should properly await async handlers
"""

import time
import threading
import requests
import asyncio
from turboapi import TurboAPI


def extract_content(response_json):
    """Extract content from response, handling both direct and wrapped formats"""
    if isinstance(response_json, dict) and "content" in response_json:
        return response_json["content"]
    return response_json


def test_sync_handler():
    """Test that sync handlers work correctly (baseline)"""
    print("\n" + "="*70)
    print("TEST 1: Sync Handler (Baseline)")
    print("="*70)
    
    app = TurboAPI(title="Sync Test")
    
    @app.post("/sync")
    def sync_handler(data: dict):
        return {"success": True, "received": data, "type": "sync"}
    
    @app.get("/sync-get")
    def sync_get():
        return {"message": "sync get works"}
    
    def start_server():
        app.run(host="127.0.0.1", port=9700)
    
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)
    
    # Test POST
    response = requests.post(
        "http://127.0.0.1:9700/sync",
        json={"test": "data"}
    )
    print(f"POST /sync: {response.status_code}")
    print(f"Response: {response.text}")
    
    assert response.status_code == 200
    assert "coroutine" not in response.text.lower()
    result = response.json()
    assert result["success"] == True
    assert result["received"]["test"] == "data"
    assert result["type"] == "sync"
    print("✅ PASSED: Sync POST handler works")
    
    # Test GET
    response = requests.get("http://127.0.0.1:9700/sync-get")
    print(f"\nGET /sync-get: {response.status_code}")
    print(f"Response: {response.text}")
    
    assert response.status_code == 200
    assert "coroutine" not in response.text.lower()
    result = response.json()
    assert result["message"] == "sync get works"
    print("✅ PASSED: Sync GET handler works")
    
    print("\n✅ SYNC HANDLER TEST PASSED!")
    return True


def test_async_handler_basic():
    """Test that async handlers are properly awaited"""
    print("\n" + "="*70)
    print("TEST 2: Async Handler (Basic)")
    print("="*70)
    
    app = TurboAPI(title="Async Test")
    
    @app.post("/async")
    async def async_handler(data: dict):
        # Simulate async operation
        await asyncio.sleep(0.01)
        return {"success": True, "received": data, "type": "async"}
    
    @app.get("/async-get")
    async def async_get():
        await asyncio.sleep(0.01)
        return {"message": "async get works"}
    
    def start_server():
        app.run(host="127.0.0.1", port=9701)
    
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)
    
    # Test POST
    response = requests.post(
        "http://127.0.0.1:9701/async",
        json={"test": "async_data"}
    )
    print(f"POST /async: {response.status_code}")
    print(f"Response: {response.text}")
    
    # CRITICAL: Should NOT contain "coroutine object"
    assert "coroutine" not in response.text.lower(), \
        f"BUG: Async handler returned coroutine object! Response: {response.text}"
    
    assert response.status_code == 200
    result = extract_content(response.json())
    assert result["success"] == True
    assert result["received"]["test"] == "async_data"
    assert result["type"] == "async"
    print("✅ PASSED: Async POST handler properly awaited")
    
    # Test GET
    response = requests.get("http://127.0.0.1:9701/async-get")
    print(f"\nGET /async-get: {response.status_code}")
    print(f"Response: {response.text}")
    
    assert "coroutine" not in response.text.lower(), \
        f"BUG: Async GET handler returned coroutine object! Response: {response.text}"
    
    assert response.status_code == 200
    result = extract_content(response.json())
    assert result["message"] == "async get works"
    print("✅ PASSED: Async GET handler properly awaited")
    
    print("\n✅ ASYNC HANDLER TEST PASSED!")
    return True


def test_async_with_query_params():
    """Test async handlers with query parameters"""
    print("\n" + "="*70)
    print("TEST 3: Async Handler with Query Params")
    print("="*70)
    
    app = TurboAPI(title="Async Query Test")
    
    @app.get("/search")
    async def async_search(q: str, limit: str = "10"):
        await asyncio.sleep(0.01)
        return {
            "query": q,
            "limit": limit,
            "results": ["result1", "result2"],
            "async": True
        }
    
    def start_server():
        app.run(host="127.0.0.1", port=9702)
    
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)
    
    response = requests.get("http://127.0.0.1:9702/search?q=turboapi&limit=20")
    print(f"GET /search?q=turboapi&limit=20: {response.status_code}")
    print(f"Response: {response.text}")
    
    assert "coroutine" not in response.text.lower(), \
        f"BUG: Async handler with query params returned coroutine! Response: {response.text}"
    
    assert response.status_code == 200
    result = response.json()
    assert result["query"] == "turboapi"
    assert result["limit"] == "20"
    assert result["async"] == True
    print("✅ PASSED: Async handler with query params works")
    
    print("\n✅ ASYNC QUERY PARAM TEST PASSED!")
    return True


def test_async_with_headers():
    """Test async handlers with headers"""
    print("\n" + "="*70)
    print("TEST 4: Async Handler with Headers")
    print("="*70)
    
    app = TurboAPI(title="Async Header Test")
    
    @app.get("/auth")
    async def async_auth(authorization: str = "none"):
        await asyncio.sleep(0.01)
        return {
            "has_auth": authorization != "none",
            "auth_type": authorization.split()[0] if " " in authorization else "none",
            "async": True
        }
    
    def start_server():
        app.run(host="127.0.0.1", port=9703)
    
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)
    
    response = requests.get(
        "http://127.0.0.1:9703/auth",
        headers={"Authorization": "Bearer token123"}
    )
    print(f"GET /auth with Authorization header: {response.status_code}")
    print(f"Response: {response.text}")
    
    assert "coroutine" not in response.text.lower(), \
        f"BUG: Async handler with headers returned coroutine! Response: {response.text}"
    
    assert response.status_code == 200
    result = response.json()
    
    # Handle both response formats (direct or wrapped)
    if "content" in result:
        result = result["content"]
    
    assert result["has_auth"] == True
    assert result["auth_type"] == "Bearer"
    assert result["async"] == True
    print("✅ PASSED: Async handler with headers works")
    
    print("\n✅ ASYNC HEADER TEST PASSED!")
    return True


def test_async_with_large_payload():
    """Test async handlers with large JSON payloads"""
    print("\n" + "="*70)
    print("TEST 5: Async Handler with Large Payload")
    print("="*70)
    
    app = TurboAPI(title="Async Large Payload Test")
    
    @app.post("/process")
    async def async_process(items: list):
        await asyncio.sleep(0.01)
        # Simulate processing
        count = len(items)
        return {
            "processed": count,
            "first_item": items[0] if items else None,
            "async": True
        }
    
    def start_server():
        app.run(host="127.0.0.1", port=9704)
    
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)
    
    # Create large payload
    large_payload = [{"id": i, "value": f"item_{i}"} for i in range(1000)]
    
    response = requests.post(
        "http://127.0.0.1:9704/process",
        json=large_payload
    )
    print(f"POST /process with 1000 items: {response.status_code}")
    print(f"Response: {response.text[:200]}...")
    
    assert "coroutine" not in response.text.lower(), \
        f"BUG: Async handler with large payload returned coroutine! Response: {response.text[:200]}"
    
    assert response.status_code == 200
    result = response.json()
    assert result["processed"] == 1000
    assert result["first_item"]["id"] == 0
    assert result["async"] == True
    print("✅ PASSED: Async handler with large payload works")
    
    print("\n✅ ASYNC LARGE PAYLOAD TEST PASSED!")
    return True


def test_mixed_sync_async():
    """Test mixing sync and async handlers in same app"""
    print("\n" + "="*70)
    print("TEST 6: Mixed Sync and Async Handlers")
    print("="*70)
    
    app = TurboAPI(title="Mixed Test")
    
    @app.get("/sync")
    def sync_endpoint():
        return {"type": "sync", "message": "I am sync"}
    
    @app.get("/async")
    async def async_endpoint():
        await asyncio.sleep(0.01)
        return {"type": "async", "message": "I am async"}
    
    @app.post("/sync-post")
    def sync_post(data: dict):
        return {"type": "sync", "received": data}
    
    @app.post("/async-post")
    async def async_post(data: dict):
        await asyncio.sleep(0.01)
        return {"type": "async", "received": data}
    
    def start_server():
        app.run(host="127.0.0.1", port=9705)
    
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)
    
    # Test all endpoints
    tests = [
        ("GET", "http://127.0.0.1:9705/sync", None, "sync"),
        ("GET", "http://127.0.0.1:9705/async", None, "async"),
        ("POST", "http://127.0.0.1:9705/sync-post", {"test": "sync"}, "sync"),
        ("POST", "http://127.0.0.1:9705/async-post", {"test": "async"}, "async"),
    ]
    
    for method, url, data, expected_type in tests:
        if method == "GET":
            response = requests.get(url)
        else:
            response = requests.post(url, json=data)
        
        print(f"\n{method} {url.split('/')[-1]}: {response.status_code}")
        print(f"Response: {response.text}")
        
        assert "coroutine" not in response.text.lower(), \
            f"BUG: {expected_type} handler returned coroutine! Response: {response.text}"
        
        assert response.status_code == 200
        result = response.json()
        assert result["type"] == expected_type
        print(f"✅ PASSED: {expected_type} endpoint works")
    
    print("\n✅ MIXED SYNC/ASYNC TEST PASSED!")
    return True


def test_async_error_handling():
    """Test that async handlers properly handle errors"""
    print("\n" + "="*70)
    print("TEST 7: Async Error Handling")
    print("="*70)
    
    app = TurboAPI(title="Async Error Test")
    
    @app.get("/error")
    async def async_error():
        await asyncio.sleep(0.01)
        raise ValueError("Intentional error for testing")
    
    @app.get("/success")
    async def async_success():
        await asyncio.sleep(0.01)
        return {"status": "success"}
    
    def start_server():
        app.run(host="127.0.0.1", port=9706)
    
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)
    
    # Test error endpoint
    response = requests.get("http://127.0.0.1:9706/error")
    print(f"GET /error: {response.status_code}")
    print(f"Response: {response.text}")
    
    # Should return error, not coroutine
    assert "coroutine" not in response.text.lower(), \
        f"BUG: Error in async handler returned coroutine! Response: {response.text}"
    
    # Should be 500 error
    assert response.status_code == 500
    print("✅ PASSED: Async error handling works")
    
    # Test success endpoint
    response = requests.get("http://127.0.0.1:9706/success")
    print(f"\nGET /success: {response.status_code}")
    print(f"Response: {response.text}")
    
    assert "coroutine" not in response.text.lower()
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "success"
    print("✅ PASSED: Async success after error works")
    
    print("\n✅ ASYNC ERROR HANDLING TEST PASSED!")
    return True


def main():
    """Run all async handler tests"""
    print("\n" + "="*70)
    print("🧪 TurboAPI Async Handler Tests - COMPREHENSIVE")
    print("="*70)
    print("Testing: Sync handlers, Async handlers, Mixed, Error handling")
    print("BUG: v0.4.13 returns coroutine objects instead of awaiting")
    print("FIX: v0.4.15 should properly await all async handlers")
    print("="*70)
    
    tests = [
        test_sync_handler,
        test_async_handler_basic,
        test_async_with_query_params,
        test_async_with_headers,
        test_async_with_large_payload,
        test_mixed_sync_async,
        test_async_error_handling,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ FAILED: {test.__name__}")
            print(f"Assertion: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ ERROR: {test.__name__}")
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "="*70)
    print(f"📊 Results: {passed} passed, {failed} failed")
    print("="*70)
    
    if failed == 0:
        print("✅ ALL ASYNC HANDLER TESTS PASSED!")
        print("\n🎉 Async handlers are working correctly!")
        return 0
    else:
        print(f"❌ {failed} test(s) failed")
        print("\n🐛 BUG CONFIRMED: Async handlers not properly awaited")
        print("   Expected: Async handlers return actual response")
        print("   Actual: Async handlers return coroutine objects")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
