#!/usr/bin/env python3
"""
Test POST Request Body Parsing with Different Patterns

Tests the fix for: https://github.com/justrach/turboAPI/issues/XXX
"""

import json
import time
import threading
import requests
from turboapi import TurboAPI
from satya import Model, Field


def test_single_dict_parameter():
    """Test Pattern 1: Single dict parameter receives entire body"""
    print("\n" + "="*70)
    print("TEST 1: Single dict parameter")
    print("="*70)
    
    app = TurboAPI(title="Test Single Dict")
    
    @app.post("/test")
    def handler(request_data: dict):
        return {"received": request_data, "type": "dict"}
    
    # Start server in thread
    def start_server():
        app.run(host="127.0.0.1", port=8091)
    
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)
    
    # Test with simple JSON
    payload = {"key": "value", "number": 42, "nested": {"data": "test"}}
    response = requests.post("http://127.0.0.1:8091/test", json=payload)
    
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    
    assert response.status_code == 200
    result = response.json()
    assert result["received"] == payload
    print("✅ PASSED: Single dict parameter works!")


def test_single_list_parameter():
    """Test Pattern 1b: Single list parameter receives entire body"""
    print("\n" + "="*70)
    print("TEST 2: Single list parameter")
    print("="*70)
    
    app = TurboAPI(title="Test Single List")
    
    @app.post("/test")
    def handler(items: list):
        return {"count": len(items), "items": items}
    
    # Start server in thread
    def start_server():
        app.run(host="127.0.0.1", port=8092)
    
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)
    
    # Test with array
    payload = [1, 2, 3, 4, 5]
    response = requests.post("http://127.0.0.1:8092/test", json=payload)
    
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    
    assert response.status_code == 200
    result = response.json()
    assert result["count"] == 5
    assert result["items"] == payload
    print("✅ PASSED: Single list parameter works!")


def test_large_json_payload():
    """Test Pattern 1c: Large JSON payload (42K items)"""
    print("\n" + "="*70)
    print("TEST 3: Large JSON payload (42K items)")
    print("="*70)
    
    app = TurboAPI(title="Test Large Payload")
    
    @app.post("/predict/backtest")
    def predict_backtest(request_data: dict):
        candles = request_data.get('candles', [])
        return {
            "success": True,
            "candles_received": len(candles),
            "symbol": request_data.get('symbol')
        }
    
    # Start server in thread
    def start_server():
        app.run(host="127.0.0.1", port=8093)
    
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)
    
    # Create large payload
    candles = [
        {
            "timestamp": 1234567890000 + i * 60000,
            "open": 100.0 + i * 0.01,
            "high": 105.0 + i * 0.01,
            "low": 95.0 + i * 0.01,
            "close": 102.0 + i * 0.01,
            "volume": 1000.0 + i
        }
        for i in range(42000)
    ]
    
    payload = {
        "symbol": "SOLUSDT",
        "candles": candles,
        "initial_capital": 10000.0,
        "position_size": 0.1
    }
    
    print(f"Sending {len(candles)} candles...")
    start_time = time.time()
    response = requests.post("http://127.0.0.1:8093/predict/backtest", json=payload)
    elapsed = time.time() - start_time
    
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    print(f"Time: {elapsed:.2f}s")
    
    assert response.status_code == 200
    result = response.json()
    assert result["success"] == True
    assert result["candles_received"] == 42000
    assert result["symbol"] == "SOLUSDT"
    print(f"✅ PASSED: Large payload (42K items) works in {elapsed:.2f}s!")


def test_satya_model_validation():
    """Test Pattern 2: Satya Model validation"""
    print("\n" + "="*70)
    print("TEST 4: Satya Model validation")
    print("="*70)
    
    class Candle(Model):
        timestamp: int = Field(ge=0)
        open: float = Field(gt=0)
        high: float = Field(gt=0)
        low: float = Field(gt=0)
        close: float = Field(gt=0)
        volume: float = Field(ge=0)
    
    class BacktestRequest(Model):
        symbol: str = Field(min_length=1)
        candles: list  # List[Candle] would be ideal but let's keep it simple
        initial_capital: float = Field(gt=0)
        position_size: float = Field(gt=0, le=1)
    
    app = TurboAPI(title="Test Satya Model")
    
    @app.post("/backtest")
    def backtest(request: BacktestRequest):
        # Use model_dump() to get actual values (Satya quirk: attributes return Field objects)
        data = request.model_dump()
        return {
            "symbol": data["symbol"],
            "candles_count": len(data["candles"]),
            "capital": data["initial_capital"]
        }
    
    # Start server in thread
    def start_server():
        app.run(host="127.0.0.1", port=8094)
    
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)
    
    # Test with valid data
    payload = {
        "symbol": "BTCUSDT",
        "candles": [
            {"timestamp": 1234567890000, "open": 100, "high": 105, "low": 95, "close": 102, "volume": 1000}
        ],
        "initial_capital": 10000.0,
        "position_size": 0.1
    }
    
    response = requests.post("http://127.0.0.1:8094/backtest", json=payload)
    
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    
    assert response.status_code == 200
    result = response.json()
    assert result["symbol"] == "BTCUSDT"
    assert result["candles_count"] == 1
    print("✅ PASSED: Satya Model validation works!")


def test_multiple_parameters():
    """Test Pattern 3: Multiple parameters (existing behavior)"""
    print("\n" + "="*70)
    print("TEST 5: Multiple parameters (existing behavior)")
    print("="*70)
    
    app = TurboAPI(title="Test Multiple Params")
    
    @app.post("/user")
    def create_user(name: str, age: int, email: str = "default@example.com"):
        return {"name": name, "age": age, "email": email}
    
    # Start server in thread
    def start_server():
        app.run(host="127.0.0.1", port=8095)
    
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)
    
    # Test with individual fields
    payload = {"name": "Alice", "age": 30, "email": "alice@example.com"}
    response = requests.post("http://127.0.0.1:8095/user", json=payload)
    
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    
    assert response.status_code == 200
    result = response.json()
    assert result["name"] == "Alice"
    assert result["age"] == 30
    print("✅ PASSED: Multiple parameters still work!")


def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("🧪 TurboAPI POST Body Parsing Tests")
    print("="*70)
    
    tests = [
        test_single_dict_parameter,
        test_single_list_parameter,
        test_large_json_payload,
        test_satya_model_validation,
        test_multiple_parameters,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ FAILED: {test.__name__}")
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "="*70)
    print(f"📊 Results: {passed} passed, {failed} failed")
    print("="*70)
    
    if failed == 0:
        print("✅ All tests passed!")
        return 0
    else:
        print(f"❌ {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
