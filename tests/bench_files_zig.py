#!/usr/bin/env python3
"""
Benchmark: Zig backend file I/O across Python 3.13 vs 3.14.

Tests:
  1. FileResponse construction (read file → build response)
  2. UploadFile round-trip (write tempfile → read back)
  3. Large binary body through turbonet ResponseView
  4. Static file path resolution
  5. Streaming-style chunked iteration

Run with:
    python3.13 tests/bench_files_zig.py
    python3.14 tests/bench_files_zig.py
"""

import os
import concurrent.futures
import sys
import time
import tempfile
import io
import json
import statistics

# ── Ensure the package is importable ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))

def banner(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")

def bench(name, fn, iterations=1000):
    """Run fn() `iterations` times, report stats."""
    # Warmup
    for _ in range(min(50, iterations)):
        fn()

    times = []
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        fn()
        times.append(time.perf_counter_ns() - t0)

    times_us = [t / 1000 for t in times]
    med = statistics.median(times_us)
    p99 = sorted(times_us)[int(len(times_us) * 0.99)]
    avg = statistics.mean(times_us)
    print(f"  {name:.<45s} avg={avg:>8.1f}µs  med={med:>8.1f}µs  p99={p99:>8.1f}µs")
    return avg


def main():
    banner(f"Python {sys.version.split()[0]} — Zig File I/O Benchmark")
    print(f"  Platform: {sys.platform} / {os.uname().machine}")
    if hasattr(sys, "_is_gil_enabled"):
        print(f"  GIL: {'enabled' if sys._is_gil_enabled() else 'DISABLED (free-threaded)'}")
    print()

    # ── Try importing the Zig turbonet ──
    try:
        from turboapi import turbonet
        has_turbonet = hasattr(turbonet, "ResponseView")
        if has_turbonet:
            print(f"  ✅ Zig turbonet loaded (ResponseView available)")
        else:
            print(f"  ⚠️  turbonet loaded but missing ResponseView")
            has_turbonet = False
    except ImportError as e:
        print(f"  ❌ turbonet not available: {e}")
        has_turbonet = False
        turbonet = None

    # ── Generate test files ──
    tmpdir = tempfile.mkdtemp(prefix="turbo_bench_")

    # Small file (4KB — typical JSON API response)
    small_path = os.path.join(tmpdir, "small.json")
    small_data = json.dumps({"users": [{"id": i, "name": f"user_{i}", "email": f"user{i}@example.com"} for i in range(50)]})
    with open(small_path, "w") as f:
        f.write(small_data)

    # Medium file (256KB — typical document)
    med_path = os.path.join(tmpdir, "medium.bin")
    med_data = os.urandom(256 * 1024)
    with open(med_path, "wb") as f:
        f.write(med_data)

    # Large file (4MB — image/PDF size)
    large_path = os.path.join(tmpdir, "large.bin")
    large_data = os.urandom(4 * 1024 * 1024)
    with open(large_path, "wb") as f:
        f.write(large_data)

    # ─────────────────────────────────────────────────────────────
    # TEST 1: File read (raw Python I/O baseline)
    # ─────────────────────────────────────────────────────────────
    banner("Test 1: Raw file read (Python I/O baseline)")

    def read_small():
        with open(small_path, "rb") as f:
            return f.read()

    def read_medium():
        with open(med_path, "rb") as f:
            return f.read()

    def read_large():
        with open(large_path, "rb") as f:
            return f.read()

    bench("small (4KB) read", read_small, 2000)
    bench("medium (256KB) read", read_medium, 1000)
    bench("large (4MB) read", read_large, 200)

    # ─────────────────────────────────────────────────────────────
    # TEST 2: FileResponse construction
    # ─────────────────────────────────────────────────────────────
    banner("Test 2: FileResponse construction (stat + read + headers)")
    from turboapi.responses import FileResponse

    def file_resp_small():
        return FileResponse(small_path, filename="data.json")

    def file_resp_medium():
        return FileResponse(med_path, filename="doc.bin")

    def file_resp_large():
        return FileResponse(large_path, filename="image.bin")

    bench("FileResponse small (4KB)", file_resp_small, 2000)
    bench("FileResponse medium (256KB)", file_resp_medium, 1000)
    bench("FileResponse large (4MB)", file_resp_large, 200)

    # ─────────────────────────────────────────────────────────────
    # TEST 3: UploadFile round-trip
    # ─────────────────────────────────────────────────────────────
    banner("Test 3: UploadFile write→read round-trip")
    from turboapi.datastructures import UploadFile
    import asyncio

    async def upload_roundtrip_small():
        uf = UploadFile(filename="test.json", content_type="application/json")
        await uf.write(small_data.encode())
        await uf.seek(0)
        data = await uf.read()
        await uf.close()
        return data

    async def upload_roundtrip_medium():
        uf = UploadFile(filename="test.bin", content_type="application/octet-stream")
        await uf.write(med_data)
        await uf.seek(0)
        data = await uf.read()
        await uf.close()
        return data

    loop = asyncio.new_event_loop()

    def sync_upload_small():
        return loop.run_until_complete(upload_roundtrip_small())

    def sync_upload_medium():
        return loop.run_until_complete(upload_roundtrip_medium())

    bench("UploadFile small (4KB) roundtrip", sync_upload_small, 1000)
    bench("UploadFile medium (256KB) roundtrip", sync_upload_medium, 500)

    # ─────────────────────────────────────────────────────────────
    # TEST 4: ResponseView binary body (Zig backend)
    # ─────────────────────────────────────────────────────────────
    if has_turbonet:
        banner("Test 4: Zig ResponseView — binary body set/get")

        def rv_binary_small():
            rv = turbonet.ResponseView(200)
            rv.set_body_bytes(small_data.encode())
            return rv.get_body_bytes()

        def rv_binary_medium():
            rv = turbonet.ResponseView(200)
            rv.set_body_bytes(med_data)
            return rv.get_body_bytes()

        def rv_binary_large():
            rv = turbonet.ResponseView(200)
            rv.set_body_bytes(large_data)
            return rv.get_body_bytes()

        bench("RV set_body_bytes small (4KB)", rv_binary_small, 5000)
        bench("RV set_body_bytes medium (256KB)", rv_binary_medium, 2000)
        bench("RV set_body_bytes large (4MB)", rv_binary_large, 500)

        # ─────────────────────────────────────────────────────────
        # TEST 5: ResponseView JSON serialization
        # ─────────────────────────────────────────────────────────
        banner("Test 5: Zig ResponseView — JSON body")

        json_payload = json.dumps({"data": list(range(500))})

        def rv_json():
            rv = turbonet.ResponseView(200)
            rv.json(json_payload)
            return rv.get_body_bytes()

        bench("RV json() (2KB payload)", rv_json, 5000)

        # ─────────────────────────────────────────────────────────
        # TEST 6: ResponseView headers
        # ─────────────────────────────────────────────────────────
        banner("Test 6: Zig ResponseView — header operations")

        def rv_headers():
            rv = turbonet.ResponseView(200)
            rv.set_header("content-type", "application/octet-stream")
            rv.set_header("content-disposition", 'attachment; filename="big.bin"')
            rv.set_header("x-request-id", "abc123-def456")
            rv.set_header("cache-control", "no-cache")
            return rv.get_header("content-type")

        bench("RV 4x set_header + get_header", rv_headers, 5000)

        # ─────────────────────────────────────────────────────────
        # TEST 6b: Concurrent ResponseView (GIL-sensitive!)
        # ─────────────────────────────────────────────────────────
        banner("Test 6b: Concurrent Zig ResponseView (no-GIL test)")

        def rv_work():
            """Build a full response — calls into C-API each time."""
            rv = turbonet.ResponseView(200)
            rv.set_header("content-type", "application/octet-stream")
            rv.set_body_bytes(med_data)
            rv.set_header("content-length", str(len(med_data)))
            _ = rv.get_body_bytes()
            return len(med_data)

        def serial_rv():
            results = []
            for _ in range(8):
                for _ in range(100):
                    rv = turbonet.ResponseView(200)
                    rv.set_header("content-type", "application/octet-stream")
                    rv.set_body_bytes(med_data)
                    rv.set_header("content-length", str(len(med_data)))
                    _ = rv.get_body_bytes()
                results.append(len(med_data))
            return results
        def concurrent_rv():
            def rv_batch():
                for _ in range(100):
                    rv = turbonet.ResponseView(200)
                    rv.set_header("content-type", "application/octet-stream")
                    rv.set_body_bytes(med_data)
                    rv.set_header("content-length", str(len(med_data)))
                    _ = rv.get_body_bytes()
                return len(med_data)
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(rv_batch) for _ in range(8)]
                return [f.result() for f in futures]
        t_s = bench("8x serial RV build (256KB body)", serial_rv, 100)
        t_p = bench("8x concurrent RV build (256KB body)", concurrent_rv, 100)
        rv_speedup = t_s / t_p if t_p > 0 else 0
        print(f"  → RV parallel speedup (8 threads): {rv_speedup:.2f}x {'🚀 TRUE PARALLELISM' if rv_speedup > 1.5 else '🔒 GIL-bound'}")


    else:
        banner("Test 4-6: SKIPPED (turbonet not loaded)")

    # ─────────────────────────────────────────────────────────────
    # TEST 7: Streaming-style chunked read
    # ─────────────────────────────────────────────────────────────
    banner("Test 7: Chunked file read (simulated streaming)")

    def chunked_read_large():
        chunks = []
        with open(large_path, "rb") as f:
            while True:
                chunk = f.read(65536)  # 64KB chunks
                if not chunk:
                    break
                chunks.append(chunk)
        return len(chunks)

    bench("chunked read large (4MB, 64KB chunks)", chunked_read_large, 200)

    # ─────────────────────────────────────────────────────────────
    # TEST 8: Concurrent file reads (threading)
    # ─────────────────────────────────────────────────────────────
    banner("Test 8: Concurrent file reads (4 threads)")

    def concurrent_reads():
        def read_file(path):
            with open(path, "rb") as f:
                return len(f.read())
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(read_file, med_path),
                executor.submit(read_file, med_path),
                executor.submit(read_file, med_path),
                executor.submit(read_file, med_path),
            ]
            return [f.result() for f in futures]

    bench("4x concurrent 256KB reads", concurrent_reads, 200)

    # ── TEST 8b: Heavy concurrent file processing (GIL-sensitive) ──
    def cpu_heavy_file_process(path):
        """Read file + do CPU work (checksum) — GIL-bound on 3.13."""
        with open(path, "rb") as f:
            data = f.read()
        # Simulate CPU-bound processing (hash-like computation)
        total = 0
        for b in data:
            total = (total * 31 + b) & 0xFFFFFFFF
        return total

    def concurrent_heavy_4():
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(cpu_heavy_file_process, med_path) for _ in range(4)]
            return [f.result() for f in futures]

    def concurrent_heavy_8():
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(cpu_heavy_file_process, med_path) for _ in range(8)]
            return [f.result() for f in futures]

    def serial_heavy_4():
        return [cpu_heavy_file_process(med_path) for _ in range(4)]

    t_serial = bench("4x serial read+process 256KB", serial_heavy_4, 20)
    t_par4 = bench("4x concurrent read+process 256KB", concurrent_heavy_4, 20)
    t_par8 = bench("8x concurrent read+process 256KB", concurrent_heavy_8, 20)
    speedup = t_serial / t_par4 if t_par4 > 0 else 0
    print(f"  → Parallel speedup (4 threads): {speedup:.2f}x {'🚀 TRUE PARALLELISM' if speedup > 1.5 else '🔒 GIL-bound'}")
    bench("4x concurrent 256KB reads", concurrent_reads, 200)

    # ─────────────────────────────────────────────────────────────
    # TEST 9: tempfile.SpooledTemporaryFile (UploadFile backend)
    # ─────────────────────────────────────────────────────────────
    banner("Test 9: SpooledTemporaryFile perf (UploadFile backend)")

    def spooled_small():
        """Stays in memory (< 1MB threshold)."""
        f = tempfile.SpooledTemporaryFile(max_size=1024*1024)
        f.write(small_data.encode())
        f.seek(0)
        data = f.read()
        f.close()
        return data

    def spooled_large_spill():
        """Spills to disk (> 1MB threshold)."""
        f = tempfile.SpooledTemporaryFile(max_size=1024*1024)
        f.write(large_data)
        f.seek(0)
        data = f.read()
        f.close()
        return data

    bench("SpooledTemp small (4KB, in-memory)", spooled_small, 2000)
    bench("SpooledTemp large (4MB, disk spill)", spooled_large_spill, 100)

    # ── Cleanup ──
    loop.close()
    for p in [small_path, med_path, large_path]:
        os.unlink(p)
    os.rmdir(tmpdir)

    banner("Done!")

if __name__ == "__main__":
    main()
