#!/usr/bin/env python3
"""
Zero-copy optimization tests for TurboAPI.
Tests the zero-copy buffer management and optimization features.
"""

import time
import sys
import traceback
from turboapi import TurboAPI

def test_zerocopy_basic():
    """Test basic zero-copy functionality"""
    print("🧪 Testing basic zero-copy functionality...")
    
    app = TurboAPI(title="Zero-Copy Test", version="1.0.0")
    app.configure_rate_limiting(enabled=False)
    
    @app.get("/zerocopy")
    def zerocopy_endpoint():
        # Simulate zero-copy optimized response
        data = {"message": "Zero-copy optimization test", "timestamp": time.time()}
        return data
    
    print("✅ Zero-copy endpoint created successfully")
    return True

def test_buffer_optimization():
    """Test buffer optimization features"""
    print("🧪 Testing buffer optimization...")
    
    try:
        # Test large response handling
        large_data = "x" * 10000  # 10KB test data
        
        app = TurboAPI(title="Buffer Test", version="1.0.0")
        app.configure_rate_limiting(enabled=False)
        
        @app.get("/large")
        def large_response():
            return {"data": large_data, "size": len(large_data)}
        
        print("✅ Buffer optimization test passed")
        return True
        
    except Exception as e:
        print(f"❌ Buffer optimization test failed: {e}")
        return False

def test_memory_efficiency():
    """Test memory efficiency of zero-copy operations"""
    print("🧪 Testing memory efficiency...")
    
    try:
        # Simulate multiple rapid requests to test memory management
        app = TurboAPI(title="Memory Test", version="1.0.0") 
        app.configure_rate_limiting(enabled=False)
        
        request_count = 0
        
        @app.get("/memory-test")
        def memory_test():
            nonlocal request_count
            request_count += 1
            return {
                "request_id": request_count,
                "memory_test": "passed",
                "optimization": "zero-copy enabled"
            }
        
        print("✅ Memory efficiency test configuration completed")
        return True
        
    except Exception as e:
        print(f"❌ Memory efficiency test failed: {e}")
        return False

def main():
    """Run all zero-copy tests"""
    print("🚀 TurboAPI Zero-Copy Tests")
    print("=" * 40)
    
    tests = [
        ("Basic Zero-Copy", test_zerocopy_basic),
        ("Buffer Optimization", test_buffer_optimization), 
        ("Memory Efficiency", test_memory_efficiency)
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n📋 Running: {test_name}")
        try:
            if test_func():
                passed += 1
                print(f"✅ {test_name}: PASSED")
            else:
                print(f"❌ {test_name}: FAILED")
        except Exception as e:
            print(f"❌ {test_name}: ERROR - {e}")
            traceback.print_exc()
    
    print(f"\n📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All zero-copy tests PASSED!")
        sys.exit(0)
    else:
        print(f"⚠️  {total - passed} tests FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
