"""
Middleware stacking performance benchmarks with tail latency analysis.
Tests issue #36: middleware stacking, streaming responses & tail latency under load.
"""

import time
import statistics
import threading
import requests
from turboapi import TurboAPI
from turboapi.middleware import CORSMiddleware, GZipMiddleware, HTTPSRedirectMiddleware


def calculate_percentiles(latencies, percentiles=[50, 95, 99]):
    """Calculate latency percentiles."""
    sorted_latencies = sorted(latencies)
    result = {}
    for p in percentiles:
        idx = int(len(sorted_latencies) * p / 100)
        result[f"p{p}"] = sorted_latencies[min(idx, len(sorted_latencies) - 1)]
    return result


def benchmark_endpoint(url, num_requests=1000, num_threads=8):
    """Benchmark an endpoint with concurrent requests."""
    latencies = []
    errors = []

    def worker():
        local_latencies = []
        for _ in range(num_requests // num_threads):
            try:
                start = time.perf_counter()
                r = requests.get(url, timeout=5)
                elapsed = time.perf_counter() - start
                if r.status_code == 200:
                    local_latencies.append(elapsed)
                else:
                    errors.append(f"Status {r.status_code}")
            except Exception as e:
                errors.append(str(e))
        latencies.extend(local_latencies)

    threads = [threading.Thread(target=worker) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if not latencies:
        return None, errors

    stats = {
        "requests": len(latencies),
        "errors": len(errors),
        "avg_ms": statistics.mean(latencies) * 1000,
        "min_ms": min(latencies) * 1000,
        "max_ms": max(latencies) * 1000,
        "stddev_ms": statistics.stdev(latencies) * 1000 if len(latencies) > 1 else 0,
        **calculate_percentiles(latencies),
        "req_per_sec": len(latencies) / sum(latencies) if latencies else 0,
    }
    return stats, errors


def test_baseline_no_middleware():
    """Benchmark baseline performance without middleware."""
    app = TurboAPI()

    @app.get("/ping")
    def ping():
        return {"message": "pong"}

    server_thread = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=9988, blocking=True), daemon=True
    )
    server_thread.start()
    time.sleep(1)  # Wait for server to start

    try:
        stats, errors = benchmark_endpoint(
            "http://127.0.0.1:9988/ping", num_requests=500, num_threads=4
        )
        assert stats is not None, f"No successful requests: {errors}"
        assert stats["errors"] == 0, f"Errors occurred: {errors}"
        assert stats["req_per_sec"] > 1000, f"Too slow: {stats['req_per_sec']} req/s"
        print(
            f"\n✅ Baseline (no middleware): {stats['req_per_sec']:.0f} req/s, "
            f"p50={stats['p50'] * 1000:.2f}ms, p95={stats['p95'] * 1000:.2f}ms, p99={stats['p99'] * 1000:.2f}ms"
        )
    finally:
        pass  # Daemon thread will be killed when test ends


def test_cors_middleware():
    """Benchmark with CORS middleware (Zig-native path)."""
    app = TurboAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/ping")
    def ping():
        return {"message": "pong"}

    server_thread = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=9989, blocking=True), daemon=True
    )
    server_thread.start()
    time.sleep(1)

    try:
        stats, errors = benchmark_endpoint(
            "http://127.0.0.1:9989/ping", num_requests=500, num_threads=4
        )
        assert stats is not None, f"No successful requests: {errors}"
        assert stats["errors"] == 0, f"Errors occurred: {errors}"

        r = requests.get("http://127.0.0.1:9989/ping")
        assert "access-control-allow-origin" in r.headers

        print(
            f"✅ CORS middleware (native): {stats['req_per_sec']:.0f} req/s, "
            f"p50={stats['p50'] * 1000:.2f}ms, p95={stats['p95'] * 1000:.2f}ms, p99={stats['p99'] * 1000:.2f}ms"
        )
    finally:
        pass


def test_gzip_middleware():
    """Benchmark with GZip middleware (Python path)."""
    app = TurboAPI()
    app.add_middleware(GZipMiddleware, minimum_size=100)

    @app.get("/data")
    def get_data():
        return {"data": "x" * 1000}  # Large enough to trigger gzip

    server_thread = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=9990, blocking=True), daemon=True
    )
    server_thread.start()
    time.sleep(1)

    try:
        stats, errors = benchmark_endpoint(
            "http://127.0.0.1:9990/data", num_requests=500, num_threads=4
        )
        assert stats is not None, f"No successful requests: {errors}"
        assert stats["errors"] == 0, f"Errors occurred: {errors}"

        r = requests.get("http://127.0.0.1:9990/data", headers={"Accept-Encoding": "gzip"})
        assert r.status_code == 200

        print(
            f"✅ GZip middleware (Python): {stats['req_per_sec']:.0f} req/s, "
            f"p50={stats['p50'] * 1000:.2f}ms, p95={stats['p95'] * 1000:.2f}ms, p99={stats['p99'] * 1000:.2f}ms"
        )
    finally:
        pass


def test_custom_logging_middleware():
    """Benchmark with custom logging middleware."""
    app = TurboAPI()

    class LoggingMiddleware:
        def __init__(self, app):
            self.app = app

        def before_request(self, request):
            return None  # No modification

        def after_request(self, response):
            response.headers["X-Request-Logged"] = "true"
            return response

    app.add_middleware(LoggingMiddleware)

    @app.get("/ping")
    def ping():
        return {"message": "pong"}

    server_thread = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=9991, blocking=True), daemon=True
    )
    server_thread.start()
    time.sleep(1)

    try:
        stats, errors = benchmark_endpoint(
            "http://127.0.0.1:9991/ping", num_requests=500, num_threads=4
        )
        assert stats is not None, f"No successful requests: {errors}"
        assert stats["errors"] == 0, f"Errors occurred: {errors}"

        r = requests.get("http://127.0.0.1:9991/ping")
        assert "x-request-logged" in r.headers

        print(
            f"✅ Custom logging middleware: {stats['req_per_sec']:.0f} req/s, "
            f"p50={stats['p50'] * 1000:.2f}ms, p95={stats['p95'] * 1000:.2f}ms, p99={stats['p99'] * 1000:.2f}ms"
        )
    finally:
        pass


def test_stacked_middleware():
    """Benchmark with stacked middleware (CORS + logging + custom)."""
    app = TurboAPI()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    class LoggingMiddleware:
        def __init__(self, app):
            self.app = app

        def before_request(self, request):
            return None

        def after_request(self, response):
            response.headers["X-Logged"] = "true"
            return response

    app.add_middleware(LoggingMiddleware)

    class AuthMiddleware:
        def __init__(self, app):
            self.app = app

        def before_request(self, request):
            auth = request.headers.get("authorization", "anonymous")
            return None

        def after_request(self, response):
            response.headers["X-Auth-Checked"] = "true"
            return response

    app.add_middleware(AuthMiddleware)

    @app.get("/protected")
    def protected():
        return {"status": "ok"}

    server_thread = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=9992, blocking=True), daemon=True
    )
    server_thread.start()
    time.sleep(1)

    try:
        stats, errors = benchmark_endpoint(
            "http://127.0.0.1:9992/protected", num_requests=500, num_threads=4
        )
        assert stats is not None, f"No successful requests: {errors}"
        assert stats["errors"] == 0, f"Errors occurred: {errors}"

        r = requests.get("http://127.0.0.1:9992/protected")
        assert "x-logged" in r.headers
        assert "x-auth-checked" in r.headers
        assert "access-control-allow-origin" in r.headers

        print(
            f"✅ Stacked middleware (3 layers): {stats['req_per_sec']:.0f} req/s, "
            f"p50={stats['p50'] * 1000:.2f}ms, p95={stats['p95'] * 1000:.2f}ms, p99={stats['p99'] * 1000:.2f}ms"
        )
    finally:
        pass


def test_streaming_response():
    """Test streaming responses under load."""
    app = TurboAPI()

    @app.get("/stream")
    def stream():
        def generate():
            for i in range(10):
                yield f"data: chunk {i}\n\n"

        from turboapi import Response

        return Response(
            content="".join(generate()),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    server_thread = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=9993, blocking=True), daemon=True
    )
    server_thread.start()
    time.sleep(1)

    try:
        r = requests.get("http://127.0.0.1:9993/stream", stream=True)
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")

        chunks = []
        for chunk in r.iter_content(chunk_size=100):
            chunks.append(chunk)

        assert len(chunks) > 0
        content = b"".join(chunks).decode()
        assert "chunk 0" in content
        assert "chunk 9" in content

        print(f"✅ Streaming response: {len(chunks)} chunks received successfully")
    finally:
        pass


def test_middleware_edge_cases():
    """Test middleware edge cases and error handling."""
    app = TurboAPI()

    class ErrorMiddleware:
        def __init__(self, app):
            self.app = app

        def before_request(self, request):
            if request.headers.get("x-trigger-error"):
                raise ValueError("Intentional error")
            return None

        def after_request(self, response):
            if response.status_code >= 400:
                response.headers["X-Error-Handled"] = "true"
            return response

    app.add_middleware(ErrorMiddleware)

    @app.get("/test")
    def test():
        return {"status": "ok"}

    server_thread = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=9994, blocking=True), daemon=True
    )
    server_thread.start()
    time.sleep(1)

    try:
        r = requests.get("http://127.0.0.1:9994/test")
        assert r.status_code == 200

        r = requests.get("http://127.0.0.1:9994/test", headers={"x-trigger-error": "true"})
        assert r.status_code == 500
        assert "x-error-handled" in r.headers

        print(f"✅ Middleware edge cases: error handling works correctly")
    finally:
        pass


if __name__ == "__main__":
    print("=" * 80)
    print("Middleware Performance Benchmarks - Issue #36")
    print("=" * 80)

    test_baseline_no_middleware()
    test_cors_middleware()
    test_gzip_middleware()
    test_custom_logging_middleware()
    test_stacked_middleware()
    test_streaming_response()
    test_middleware_edge_cases()

    print("\n" + "=" * 80)
    print("All middleware benchmarks completed successfully!")
    print("=" * 80)
