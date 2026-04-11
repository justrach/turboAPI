#!/usr/bin/env python3
"""
Regression benchmark — run after every perf change to catch regressions.

Outputs machine-readable JSON + human summary. Fails if any endpoint
drops below its threshold.

Usage:
    uv run --python 3.14t python benchmarks/bench_regression.py
    uv run --python 3.14t python benchmarks/bench_regression.py --save   # save as new baseline
    uv run --python 3.14t python benchmarks/bench_regression.py --ci     # exit(1) on regression
    uv run --python 3.14t python benchmarks/bench_regression.py --history # save history snapshot
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
BASELINE_FILE = os.path.join(BENCH_DIR, "baseline.json")
THRESHOLDS_FILE = os.path.join(BENCH_DIR, "thresholds.json")
HISTORY_DIR = os.path.join(BENCH_DIR, "history")
RESULTS_FILE = "/tmp/bench_results.json"
PR_COMMENT_FILE = "/tmp/bench_pr_comment.md"

DURATION = int(os.environ.get("BENCH_DURATION", "10"))
THREADS = int(os.environ.get("BENCH_THREADS", "4"))
CONNECTIONS = int(os.environ.get("BENCH_CONNECTIONS", "100"))

SERVER_CODE = """
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
"""

BENCHMARKS = [
    ("GET /health", "/health", "GET", None),
    ("GET /", "/", "GET", None),
    ("GET /json", "/json", "GET", None),
    ("GET /users/123", "/users/123", "GET", None),
    ("POST /items", "/items", "POST", '{"name":"Widget","price":9.99}'),
    ("GET /status201", "/status201", "GET", None),
]


def parse_wrk(output: str) -> dict:
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
            f.write(
                f'wrk.method = "POST"\nwrk.headers["Content-Type"] = "application/json"\nwrk.body = \'{body}\'\n'
            )
    cmd.append(url)
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    return parse_wrk(out)


def load_thresholds_config():
    if os.path.exists(THRESHOLDS_FILE):
        with open(THRESHOLDS_FILE) as f:
            return json.load(f)
    return {"margin_pct": 10, "average_threshold_rps": 130000, "endpoints": {}}


def load_thresholds(ci_mode=False):
    config = load_thresholds_config()
    endpoint_thresholds = {}

    if ci_mode and "ci" in config:
        active = config["ci"]
    else:
        active = config

    margin = active.get("margin_pct", config.get("margin_pct", 10)) / 100.0

    if not (ci_mode and "ci" in config):
        if os.path.exists(BASELINE_FILE):
            with open(BASELINE_FILE) as f:
                baseline = json.load(f)
            for k, v in baseline.items():
                endpoint_thresholds[k] = int(v * (1 - margin))

    for k, v in active.get("endpoints", {}).items():
        min_rps = v.get("min_rps", 0)
        if k not in endpoint_thresholds or min_rps > endpoint_thresholds[k]:
            endpoint_thresholds[k] = min_rps

    return endpoint_thresholds, active.get(
        "average_threshold_rps", config.get("average_threshold_rps", 130000)
    )


def save_history(results, detailed=None):
    os.makedirs(HISTORY_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")  # noqa: UP017
    history_file = os.path.join(HISTORY_DIR, f"{ts}.json")
    payload = {
        "timestamp": ts,
        "results": results,
        "detailed": detailed or {},
        "commit": os.popen("git rev-parse HEAD 2>/dev/null").read().strip() or "unknown",
        "runner": os.environ.get("BENCH_RUNNER", "local"),
        "os": os.environ.get("BENCH_OS", "unknown"),
        "vcpus": os.environ.get("BENCH_VCPUS", "unknown"),
        "duration": DURATION,
        "threads": THREADS,
        "connections": CONNECTIONS,
    }
    with open(history_file, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"History snapshot saved to {history_file}")


def generate_pr_comment(results, detailed, thresholds, avg_threshold, regressions):
    runner = os.environ.get("BENCH_RUNNER", "local")
    duration = DURATION
    lines = ["## Performance Regression Report\n"]
    lines.append(
        f"> Runner: **{runner}** | Duration: **{duration}s** per endpoint | Threads: **{THREADS}** | Connections: **{CONNECTIONS}**\n"
    )
    lines.append("| Endpoint | req/s | avg latency | p99 latency | threshold | status |")
    lines.append("|----------|------:|------------:|------------:|----------:|--------|")
    for name, path, method, body in BENCHMARKS:
        d = detailed.get(name, {})
        rps = d.get("requests_per_second", 0)
        avg_l = d.get("latency_avg_ms", 0)
        p99_l = d.get("latency_p99_ms", 0)
        thresh = thresholds.get(name, 0)
        status = "REGRESSED" if any(r[0] == name for r in regressions) else "OK"
        lines.append(
            f"| {name} | {rps:,.0f} | {avg_l:.2f}ms | {p99_l:.2f}ms | {thresh:,} | {status} |"
        )
    avg = sum(r.get("requests_per_second", 0) for r in detailed.values()) / max(len(detailed), 1)
    lines.append(
        f"| **AVERAGE** | **{avg:,.0f}** | | | **{avg_threshold:,}** | {'REGRESSED' if avg < avg_threshold else 'OK'} |"
    )
    lines.append("")
    if regressions:
        lines.append(f"> :warning: **{len(regressions)} endpoint(s) below threshold**")
    else:
        lines.append("> :white_check_mark: All endpoints pass regression thresholds")
    comment = "\n".join(lines)
    with open(PR_COMMENT_FILE, "w") as f:
        f.write(comment)
    return comment


def main():
    save_mode = "--save" in sys.argv
    ci_mode = "--ci" in sys.argv
    history_mode = "--history" in sys.argv

    with open("/tmp/turboapi_regbench.py", "w") as f:
        f.write(SERVER_CODE)

    import urllib.error
    import urllib.request

    env = os.environ.copy()
    env["PYTHON_GIL"] = "0"
    env["TURBO_DISABLE_RATE_LIMITING"] = "1"
    env["TURBO_DISABLE_CACHE"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "/tmp/turboapi_regbench.py"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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

    time.sleep(1)

    results = {}
    detailed = {}
    print(f"{'Endpoint':<25} {'req/s':>10} {'avg':>8} {'p99':>8} {'status':>8}")
    print("-" * 65)

    thresholds, avg_threshold = load_thresholds(ci_mode=ci_mode)
    regressions = []

    for name, path, method, body in BENCHMARKS:
        url = f"http://127.0.0.1:8001{path}"
        r = run_wrk(url, method, body)
        rps = r["requests_per_second"]
        results[name] = rps
        detailed[name] = r

        threshold = thresholds.get(name, 0)
        passed = rps >= threshold
        status = "OK" if passed else "REGRESSED"
        if not passed:
            regressions.append((name, rps, threshold))

        print(
            f"{name:<25} {rps:>10,.0f} {r['latency_avg_ms']:>6.2f}ms {r['latency_p99_ms']:>6.2f}ms {status:>8}"
        )

    proc.kill()
    proc.wait()

    print("-" * 65)
    avg = sum(results.values()) / len(results)
    print(f"{'AVERAGE':<25} {avg:>10,.0f}")

    avg_regressed = avg < avg_threshold
    if avg_regressed:
        regressions.append(("AVERAGE", avg, avg_threshold))
        print(f"  AVERAGE {avg:,.0f} < {avg_threshold:,} (threshold)")

    if save_mode:
        with open(BASELINE_FILE, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nBaseline saved to {BASELINE_FILE}")

    with open(RESULTS_FILE, "w") as f:
        json.dump({"results": results, "detailed": detailed}, f, indent=2)

    if history_mode or save_mode:
        save_history(results, detailed)

    if ci_mode:
        generate_pr_comment(results, detailed, thresholds, avg_threshold, regressions)

    if regressions:
        print(f"\n{'!' * 60}")
        print(f"REGRESSION DETECTED in {len(regressions)} endpoint(s):")
        for name, actual, threshold in regressions:
            print(f"  {name}: {actual:,.0f} < {threshold:,.0f} (threshold)")
        print(f"{'!' * 60}")
        if ci_mode:
            sys.exit(1)

    return results


if __name__ == "__main__":
    main()
