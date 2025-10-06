#!/bin/bash
# Quick benchmark: TurboAPI v0.3.21 vs FastAPI

echo "=========================================="
echo "🏁 TurboAPI v0.3.21 vs FastAPI Benchmark"
echo "=========================================="
echo ""

# Check for wrk
if ! command -v wrk &> /dev/null; then
    echo "❌ wrk not found. Install with: brew install wrk"
    exit 1
fi

# Test TurboAPI
echo "🚀 Starting TurboAPI v0.3.21..."
python tests/test_v0_3_20_server.py > /tmp/turbo.log 2>&1 &
TURBO_PID=$!
sleep 4

echo "📊 Benchmarking TurboAPI (10s, 4 threads, 100 connections)..."
echo ""
echo "Test 1: Simple GET /"
wrk -t4 -c100 -d10s --latency http://127.0.0.1:8080/ 2>&1 | grep -E "Requests/sec|Latency|Thread"

echo ""
echo "Test 2: Parameterized route /users/123"
wrk -t4 -c100 -d10s --latency http://127.0.0.1:8080/users/123 2>&1 | grep -E "Requests/sec|Latency|Thread"

echo ""
echo "Test 3: Nested params /api/v1/users/1/posts/2"
wrk -t4 -c100 -d10s --latency http://127.0.0.1:8080/api/v1/users/1/posts/2 2>&1 | grep -E "Requests/sec|Latency|Thread"

kill $TURBO_PID 2>/dev/null
sleep 2

# Test FastAPI
echo ""
echo "=========================================="
echo "🚀 Starting FastAPI..."
python tests/fastapi_v0_3_20_equivalent.py > /tmp/fastapi.log 2>&1 &
FASTAPI_PID=$!
sleep 4

echo "📊 Benchmarking FastAPI (10s, 4 threads, 100 connections)..."
echo ""
echo "Test 1: Simple GET /"
wrk -t4 -c100 -d10s --latency http://127.0.0.1:8081/ 2>&1 | grep -E "Requests/sec|Latency|Thread"

echo ""
echo "Test 2: Parameterized route /users/123"
wrk -t4 -c100 -d10s --latency http://127.0.0.1:8081/users/123 2>&1 | grep -E "Requests/sec|Latency|Thread"

echo ""
echo "Test 3: Nested params /api/v1/users/1/posts/2"
wrk -t4 -c100 -d10s --latency http://127.0.0.1:8081/api/v1/users/1/posts/2 2>&1 | grep -E "Requests/sec|Latency|Thread"

kill $FASTAPI_PID 2>/dev/null

echo ""
echo "=========================================="
echo "✅ Benchmark Complete!"
echo "=========================================="
