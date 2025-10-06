#!/bin/bash
# Async benchmark: TurboAPI v0.3.21 SYNC vs ASYNC vs FastAPI

echo "=========================================="
echo "🏁 TurboAPI v0.3.21: SYNC vs ASYNC vs FastAPI"
echo "=========================================="
echo ""

# Check for wrk
if ! command -v wrk &> /dev/null; then
    echo "❌ wrk not found. Install with: brew install wrk"
    exit 1
fi

# Test TurboAPI SYNC
echo "🚀 Test 1: TurboAPI SYNC (baseline)"
echo "=========================================="
python tests/test_v0_3_20_server.py > /tmp/turbo_sync.log 2>&1 &
TURBO_SYNC_PID=$!
sleep 4

echo "Simple GET:"
wrk -t4 -c100 -d10s http://127.0.0.1:8080/ 2>&1 | grep "Requests/sec"
echo "Parameterized:"
wrk -t4 -c100 -d10s http://127.0.0.1:8080/users/123 2>&1 | grep "Requests/sec"

kill $TURBO_SYNC_PID 2>/dev/null
sleep 2

# Test TurboAPI ASYNC
echo ""
echo "🚀 Test 2: TurboAPI ASYNC (asyncio.run)"
echo "=========================================="
python tests/test_async_benchmark.py > /tmp/turbo_async.log 2>&1 &
TURBO_ASYNC_PID=$!
sleep 4

echo "Simple GET:"
wrk -t4 -c100 -d10s http://127.0.0.1:8082/ 2>&1 | grep "Requests/sec"
echo "Parameterized:"
wrk -t4 -c100 -d10s http://127.0.0.1:8082/users/123 2>&1 | grep "Requests/sec"

kill $TURBO_ASYNC_PID 2>/dev/null
sleep 2

# Test FastAPI
echo ""
echo "🚀 Test 3: FastAPI (async with uvicorn)"
echo "=========================================="
python tests/fastapi_v0_3_20_equivalent.py > /tmp/fastapi.log 2>&1 &
FASTAPI_PID=$!
sleep 4

echo "Simple GET:"
wrk -t4 -c100 -d10s http://127.0.0.1:8081/ 2>&1 | grep "Requests/sec"
echo "Parameterized:"
wrk -t4 -c100 -d10s http://127.0.0.1:8081/users/123 2>&1 | grep "Requests/sec"

kill $FASTAPI_PID 2>/dev/null

echo ""
echo "=========================================="
echo "✅ Benchmark Complete!"
echo "=========================================="
