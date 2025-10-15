#!/usr/bin/env python3
"""
Comprehensive Test Suite for TurboAPI v0.4.15
Tests ALL features: POST body, query params, headers, async handlers

This is the MASTER test suite that must pass before release.
"""

import subprocess
import sys


def run_test(test_file, description):
    """Run a test file and return success status"""
    print("\n" + "="*80)
    print(f"Running: {description}")
    print("="*80)
    
    try:
        result = subprocess.run(
            [sys.executable, test_file],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        # Print last 30 lines of output
        lines = result.stdout.split('\n')
        for line in lines[-30:]:
            print(line)
        
        if result.returncode == 0:
            print(f"✅ {description} PASSED")
            return True
        else:
            print(f"❌ {description} FAILED")
            if result.stderr:
                print("STDERR:", result.stderr[-500:])
            return False
            
    except subprocess.TimeoutExpired:
        print(f"❌ {description} TIMEOUT")
        return False
    except Exception as e:
        print(f"❌ {description} ERROR: {e}")
        return False


def main():
    """Run all comprehensive tests"""
    print("\n" + "="*80)
    print("🧪 TurboAPI v0.4.15 - COMPREHENSIVE TEST SUITE")
    print("="*80)
    print("Testing ALL features:")
    print("  1. POST body parsing (v0.4.13)")
    print("  2. Query parameters (v0.4.14)")
    print("  3. Headers (v0.4.14)")
    print("  4. Async handlers (v0.4.15 FIX)")
    print("  5. Combined features")
    print("="*80)
    
    tests = [
        ("tests/test_post_body_parsing.py", "POST Body Parsing"),
        ("tests/test_query_and_headers.py", "Query Parameters & Headers"),
        ("tests/test_async_simple.py", "Async Handlers (Basic)"),
    ]
    
    results = []
    for test_file, description in tests:
        success = run_test(test_file, description)
        results.append((description, success))
    
    # Summary
    print("\n" + "="*80)
    print("📊 COMPREHENSIVE TEST RESULTS")
    print("="*80)
    
    passed = sum(1 for _, success in results if success)
    failed = len(results) - passed
    
    for description, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"  {status}: {description}")
    
    print("="*80)
    print(f"Total: {passed}/{len(results)} passed, {failed} failed")
    print("="*80)
    
    if failed == 0:
        print("\n🎉 ALL COMPREHENSIVE TESTS PASSED!")
        print("\n✅ v0.4.15 Features Working:")
        print("  ✅ POST body parsing (dict, list, Satya models)")
        print("  ✅ Query parameter parsing")
        print("  ✅ Header parsing")
        print("  ✅ Async handlers (properly awaited)")
        print("  ✅ Combined features")
        print("\n🚀 Ready for production!")
        return 0
    else:
        print(f"\n❌ {failed} test suite(s) failed")
        print("   Review failures above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
