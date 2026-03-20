"""
Benchmark for Issue #36: Tail latency under load with stacked middleware and streaming.
Requires `wrk` to be installed on the system.
"""
import asyncio
import os
import subprocess
import time
from threading import Thread

from turboapi import TurboAPI
from turboapi.middleware import CORSMiddleware, LoggingMiddleware
try:
    from turboapi.responses import StreamingResponse
except ImportError:
    StreamingResponse = None

app = TurboAPI(title="Middleware & Streaming Benchmark")

# 1. Stacked Middleware Setup (Auth/Logging + CORS)
app.add_middleware(LoggingMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=["*"])

@app.get("/stacked")
def stacked_endpoint():
    return {"message": "Hello with stacked middleware", "status": "ok"}

# 2. Streaming Setup
@app.get("/stream")
async def stream_endpoint():
    async def generator():
        for i in range(50):
            yield f"data: chunk {i}\n\n".encode()
            await asyncio.sleep(0.001)
    
    if StreamingResponse:
        return StreamingResponse(generator())
    return {"error": "StreamingResponse not available"}

def run_server():
    # Run silently to not pollute benchmark output with LoggingMiddleware prints
    import sys
    sys.stdout = open(os.devnull, 'w')
    app.run(host="127.0.0.1", port=8085)

if __name__ == "__main__":
    print("Starting TurboAPI server for tail-latency benchmarks...")
    server_thread = Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(2)  # Wait for server to bind

    print("\n" + "="*50)
    print(" TEST 1: Stacked Middleware (CORS + Logging)")
    print("="*50)
    try:
        # --latency flag forces wrk to print latency percentiles (p50, p75, p90, p99)
        subprocess.run([
            "wrk", "-t4", "-c100", "-d15s", "--latency", "http://127.0.0.1:8085/stacked"
        ], check=True)
    except FileNotFoundError:
        print("'wrk' not found. Please install wrk (e.g., `brew install wrk` or `apt install wrk`).")

    if StreamingResponse:
        print("\n" + "="*50)
        print(" TEST 2: Chunked Streaming Endpoint")
        print("="*50)
        try:
            subprocess.run([
                "wrk", "-t4", "-c100", "-d15s", "--latency", "http://127.0.0.1:8085/stream"
            ], check=True)
        except FileNotFoundError:
            pass

    print("\n Benchmarks complete. Terminating server.")
    os._exit(0)