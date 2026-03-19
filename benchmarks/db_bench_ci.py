#!/usr/bin/env python3
"""
DB Benchmark for CI — TurboAPI+pg.zig vs FastAPI+SQLAlchemy.

Outputs structured results for regression testing.
Expects Postgres running on 127.0.0.1:5432 with turbotest DB seeded.
"""

import os
import re
import signal
import subprocess
import sys
import time
import urllib.request

DB_URL = os.environ.get("DATABASE_URL", "postgres://turbo:turbo@127.0.0.1:5432/turbotest")
TURBO_PORT = 8100
FASTAPI_PORT = 8200
WRK_THREADS = 2
WRK_CONNECTIONS = 50
WRK_DURATION = "10s"

procs = []


def start_turbo():
    """Start TurboAPI with pg.zig."""
    code = f"""
import os, sys
sys.path.insert(0, 'python')
from dhi import BaseModel, Field
from turboapi import TurboAPI

app = TurboAPI()
app.configure_db('{DB_URL}', pool_size=16)

class User(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str
    age: int = Field(gt=0, le=150)

@app.db_get('/users/{{user_id}}', table='users', pk='id')
def get_user(): pass

@app.db_list('/users', table='users')
def list_users(): pass

@app.db_post('/users', table='users', model=User)
def create_user(): pass

@app.get('/health')
def health():
    return {{'status': 'ok'}}

app.run(host='127.0.0.1', port={TURBO_PORT})
"""
    p = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    procs.append(p)
    return p


def start_fastapi():
    """Start FastAPI with SQLAlchemy."""
    code = f"""
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

DB = '{DB_URL}'.replace('postgres://', 'postgresql://')
engine = create_engine(DB, pool_size=16)
app = FastAPI()

class UserIn(BaseModel):
    name: str
    email: str
    age: int

@app.get('/users/{{user_id}}')
def get_user(user_id: int):
    with Session(engine) as s:
        r = s.execute(text('SELECT id,name,email,age FROM users WHERE id=:id'), {{'id': user_id}}).fetchone()
        if not r: return {{'error': 'Not found'}}
        return {{'id': r[0], 'name': r[1], 'email': r[2], 'age': r[3]}}

@app.get('/users')
def list_users(limit: int = 50, offset: int = 0):
    with Session(engine) as s:
        rows = s.execute(text('SELECT id,name,email,age FROM users LIMIT :l OFFSET :o'), {{'l': limit, 'o': offset}}).fetchall()
        return [{{'id': r[0], 'name': r[1], 'email': r[2], 'age': r[3]}} for r in rows]

@app.get('/health')
def health():
    return {{'status': 'ok'}}

uvicorn.run(app, host='127.0.0.1', port={FASTAPI_PORT}, log_level='error')
"""
    p = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    procs.append(p)
    return p


def wait_for(port, timeout=15):
    for _ in range(timeout * 10):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def run_wrk(port, path, label):
    """Run wrk and extract req/s and latency."""
    url = f"http://127.0.0.1:{port}{path}"
    try:
        result = subprocess.run(
            ["wrk", f"-t{WRK_THREADS}", f"-c{WRK_CONNECTIONS}", f"-d{WRK_DURATION}", url],
            capture_output=True,
            text=True,
            timeout=30,
        )
        rps = 0.0
        lat = ""
        for line in result.stdout.splitlines():
            if "Requests/sec" in line:
                m = re.search(r"([\d.]+)", line.split("Requests/sec")[0].strip().split()[-1])
                if not m:
                    m = re.search(r"Requests/sec:\s*([\d.]+)", line)
                if m:
                    rps = float(m.group(1))
            if "Latency" in line and "Distribution" not in line:
                lat = line.strip()
        return rps, lat
    except Exception as e:
        return 0.0, f"error: {e}"


def main():
    print()
    print("=" * 70)
    print("  TurboAPI+pg.zig vs FastAPI+SQLAlchemy — DB Benchmark (Postgres 18)")
    print("=" * 70)
    print(f"  wrk: {WRK_THREADS} threads, {WRK_CONNECTIONS} connections, {WRK_DURATION}")
    print(f"  Python: {sys.version.split()[0]}")
    print()

    # Start servers
    print("  Starting TurboAPI (pg.zig)...", end=" ", flush=True)
    start_turbo()
    if wait_for(TURBO_PORT):
        print("OK")
    else:
        print("FAILED")
        sys.exit(1)

    print("  Starting FastAPI (SQLAlchemy)...", end=" ", flush=True)
    start_fastapi()
    if wait_for(FASTAPI_PORT):
        print("OK")
    else:
        print("FAILED (continuing with TurboAPI only)")

    # Warm cache
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{TURBO_PORT}/users/1")
        urllib.request.urlopen(f"http://127.0.0.1:{TURBO_PORT}/users?limit=10")
    except Exception:
        pass

    print()
    results = {}

    # Benchmark matrix
    tests = [
        ("turbo_cached_pk", TURBO_PORT, "/users/1", "TurboAPI cached GET /users/1"),
        ("turbo_cached_list", TURBO_PORT, "/users?limit=10", "TurboAPI cached GET /users?limit=10"),
        ("turbo_health", TURBO_PORT, "/health", "TurboAPI GET /health (no DB)"),
        ("fastapi_pk", FASTAPI_PORT, "/users/1", "FastAPI GET /users/1"),
        ("fastapi_list", FASTAPI_PORT, "/users?limit=10", "FastAPI GET /users?limit=10"),
        ("fastapi_health", FASTAPI_PORT, "/health", "FastAPI GET /health (no DB)"),
    ]

    for key, port, path, label in tests:
        if not wait_for(port, timeout=1):
            print(f"  {label:45s}  (server not running)")
            continue
        rps, lat = run_wrk(port, path, label)
        results[key] = rps
        print(f"  {key:30s}: {rps:>10.0f} req/s  |  {lat}")

    print()

    # Summary
    tp = results.get("turbo_cached_pk", 0)
    fp = results.get("fastapi_pk", 0)
    tl = results.get("turbo_cached_list", 0)
    fl = results.get("fastapi_list", 0)
    if fp > 0:
        print(f"  Speedup (cached PK):   {tp/fp:.1f}x  ({tp:.0f} vs {fp:.0f} req/s)")
    if fl > 0:
        print(f"  Speedup (cached list): {tl/fl:.1f}x  ({tl:.0f} vs {fl:.0f} req/s)")

    print()
    print("=" * 70)

    # Cleanup
    for p in procs:
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=5)

    # Exit with error if turbo is way below expected
    if tp < 10000:
        print("WARNING: TurboAPI cached PK below 10k req/s — possible regression")
        sys.exit(1)


if __name__ == "__main__":
    main()
