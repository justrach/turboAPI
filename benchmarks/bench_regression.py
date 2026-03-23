#!/usr/bin/env python3
"""
Regression benchmark — run after every perf change to catch regressions.

Outputs machine-readable JSON + human summary. Fails if any endpoint
drops below its threshold.

Usage:
    uv run --python 3.14t python benchmarks/bench_regression.py
    uv run --python 3.14t python benchmarks/bench_regression.py --save   # save as new baseline
    uv run --python 3.14t python benchmarks/bench_regression.py --ci     # exit(1) on regression
"""

import json
import os
import subprocess
import sys
import time

BASELINE_FILE = os.path.join(os.path.dirname(__file__), "baseline.json")

# Minimum acceptable req/s per endpoint (updated by --save)
DEFAULT_THRESHOLDS = {
    "GET /health": 130_000,
    "GET /": 125_000,
    "GET /json": 125_000,
    "GET /users/123": 125_000,
    "POST /items": 110_000,
    "GET /status201": 125_000,
}

DURATION = 10
THREADS = 4
CONNECTIONS = 100

SERVER_CODE = '''
from turboapi import TurboAPI, JSONResponse
from dhi import BaseModel
from typing import Optional

app = TurboAPI()

class Item(BaseModel):
    name: str
    price: float
    description: Optional[str] = None

@app.get("/health")
def health():
    return {"status":"ok","engine":"turbo"}

@app.get("/")
def root():
    return {"message": "Hello, World!"}

@app.get("/json")
def json_response():
    return {"data": [1, 2, 3, 4, 5], "status": "ok", "count": 5}

@app.get("/users/{user_id}")
def get_user(user_id: int):
    return {"user_id": user_id, "name": f"User {user_id}"}

@app.post("/items")
def create_item(item: Item):
    return {"created": True, "item": item.model_dump()}

@app.get("/status201")
def status_201():
    return JSONResponse(content={"created": True}, status_code=201)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8001)
'''

BENCHMARKS = [
    ("GET /health", "/health", "GET", None),
    ("GET /", "/", "GET", None),
    ("GET /json", "/json", "GET", None),
    ("GET /users/123", "/users/123", "GET", None),
    ("POST /items", "/items", "POST", '{"name":"Widget","price":9.99}'),
    ("GET /status201", "/status201", "GET", None),
]


def parse_wrk(output: str) -> dict:
    """Parse wrk output into structured data."""
    result = {"requests_per_second": 0, "latency_avg_ms": 0, "latency_p99_ms": 0}
    for line in output.split("\n"):
        line = line.strip()
        if "Requests/sec:" in line:
            result["requests_per_second"] = float(line.split(":")[1].strip())
        elif "Latency" in line and "Stdev" not in line and "Distribution" not in line:
            parts = line.split()
            if len(parts) >= 2:
                val = parts[1]
                if val.endswith("ms"):
                    result["latency_avg_ms"] = float(val[:-2])
                elif val.endswith("us"):
                    result["latency_avg_ms"] = float(val[:-2]) / 1000
                elif val.endswith("s"):
                    result["latency_avg_ms"] = float(val[:-1]) * 1000
        elif "99%" in line:
            val = line.split()[-1] if line.split() else "0"
            if val.endswith("ms"):
                result["latency_p99_ms"] = float(val[:-2])
            elif val.endswith("us"):
                result["latency_p99_ms"] = float(val[:-2]) / 1000
            elif val.endswith("s"):
                result["latency_p99_ms"] = float(val[:-1]) * 1000
    return result


def run_wrk(url, method="GET", body=None):
    cmd = ["wrk", "-t", str(THREADS), "-c", str(CONNECTIONS), "-d", f"{DURATION}s", "--latency"]
    if method == "POST" and body:
        cmd += ["-s", "/tmp/_bench_post.lua"]
        with open("/tmp/_bench_post.lua", "w") as f:
            f.write(f'wrk.method = "POST"\nwrk.headers["Content-Type"] = "application/json"\nwrk.body = \'{body}\'\n')
    cmd.append(url)
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    return parse_wrk(out)


def load_thresholds():
    if os.path.exists(BASELINE_FILE):
        with open(BASELINE_FILE) as f:
            data = json.load(f)
        return {k: int(v * 0.90) for k, v in data.items()}  # 10% margin
    return DEFAULT_THRESHOLDS


def main():
    save_mode = "--save" in sys.argv
    ci_mode = "--ci" in sys.argv

    with open("/tmp/turboapi_regbench.py", "w") as f:
        f.write(SERVER_CODE)

    # Start server
    import urllib.error
    import urllib.request

    env = os.environ.copy()
    env["PYTHON_GIL"] = "0"
    env["TURBO_DISABLE_RATE_LIMITING"] = "1"
    env["TURBO_DISABLE_CACHE"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "/tmp/turboapi_regbench.py"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            urllib.request.urlopen("http://127.0.0.1:8001/", timeout=1)
            break
        except (urllib.error.URLError, ConnectionRefusedError):
            time.sleep(0.2)
    else:
        proc.kill()
        print("FAIL: server didn't start")
        sys.exit(1)

    time.sleep(1)  # warmup

    # Run benchmarks
    results = {}
    print(f"{'Endpoint':<25} {'req/s':>10} {'avg':>8} {'p99':>8} {'status':>8}")
    print("-" * 65)

    thresholds = load_thresholds()
    regressions = []

    for name, path, method, body in BENCHMARKS:
        url = f"http://127.0.0.1:8001{path}"
        r = run_wrk(url, method, body)
        rps = r["requests_per_second"]
        results[name] = rps

        threshold = thresholds.get(name, 0)
        passed = rps >= threshold
        status = "OK" if passed else "REGRESSED"
        if not passed:
            regressions.append((name, rps, threshold))

        print(f"{name:<25} {rps:>10,.0f} {r['latency_avg_ms']:>6.2f}ms {r['latency_p99_ms']:>6.2f}ms {status:>8}")

    proc.kill()
    proc.wait()

    print("-" * 65)
    avg = sum(results.values()) / len(results)
    print(f"{'AVERAGE':<25} {avg:>10,.0f}")

    if save_mode:
        with open(BASELINE_FILE, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nBaseline saved to {BASELINE_FILE}")

    # Machine-readable output
    with open("/tmp/bench_results.json", "w") as f:
        json.dump(results, f, indent=2)

    if regressions:
        print(f"\n{'!'*60}")
        print(f"REGRESSION DETECTED in {len(regressions)} endpoint(s):")
        for name, actual, threshold in regressions:
            print(f"  {name}: {actual:,.0f} < {threshold:,.0f} (threshold)")
        print(f"{'!'*60}")
        if ci_mode:
            sys.exit(1)

    return results


if __name__ == "__main__":
    main()
