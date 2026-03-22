#!/usr/bin/env python3
"""
End-to-end HTTP + DB benchmark.

Compares:
1. TurboAPI + pg.zig/turbopg
2. FastAPI + asyncpg
3. FastAPI + SQLAlchemy

All three expose the same HTTP routes. TurboAPI runs with both the HTTP
response cache and DB cache disabled so the benchmark measures uncached
request -> query -> serialization throughput.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.request
from dataclasses import dataclass

DB_URL = os.environ.get("BENCH_PG_URL", "postgresql://bench:bench@127.0.0.1:5432/bench")
WRK_DURATION = os.environ.get("BENCH_DURATION", "10s")
WRK_THREADS = 4
WRK_CONNECTIONS = 100


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def parse_wrk(output: str) -> tuple[float, str]:
    rps = 0.0
    lat = ""
    for line in output.splitlines():
        if "Requests/sec:" in line:
            match = re.search(r"Requests/sec:\s*([\d.]+)", line)
            if match:
                rps = float(match.group(1))
        if "Latency" in line and "Distribution" not in line:
            lat = line.strip()
    return rps, lat


def run_wrk(url: str, label: str) -> tuple[float, str]:
    result = subprocess.run(
        ["wrk", f"-t{WRK_THREADS}", f"-c{WRK_CONNECTIONS}", f"-d{WRK_DURATION}", url],
        capture_output=True,
        text=True,
        timeout=120,
    )
    rps, lat = parse_wrk(result.stdout)
    print(f"  {label}: {rps:,.0f} req/s  |  {lat}", flush=True)
    return rps, lat


def run_wrk_lua(url: str, lua_path: str, label: str) -> tuple[float, str]:
    result = subprocess.run(
        ["wrk", f"-t{WRK_THREADS}", f"-c{WRK_CONNECTIONS}", f"-d{WRK_DURATION}", "-s", lua_path, url],
        capture_output=True,
        text=True,
        timeout=120,
    )
    rps, lat = parse_wrk(result.stdout)
    print(f"  {label}: {rps:,.0f} req/s  |  {lat}", flush=True)
    return rps, lat


def wait_for(port: int, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def warmup(port: int) -> None:
    paths = [
        "/health",
        "/users/1",
        "/users?age_min=20",
        "/search?q=user_42%25",
    ]
    for path in paths:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2).read()
        except Exception:
            pass


@dataclass
class ServerHandle:
    name: str
    proc: subprocess.Popen[str]
    port: int
    err_path: str


def start_server(name: str, code: str) -> ServerHandle:
    port = free_port()
    rendered = code.format(db_url=DB_URL, port=port)
    err_file = tempfile.NamedTemporaryFile(mode="w", suffix=f".{name}.log", delete=False)
    proc = subprocess.Popen(
        [sys.executable, "-c", rendered],
        stdout=subprocess.DEVNULL,
        stderr=err_file,
        text=True,
    )
    return ServerHandle(name=name, proc=proc, port=port, err_path=err_file.name)


def stop_server(handle: ServerHandle) -> None:
    handle.proc.kill()
    try:
        handle.proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        handle.proc.kill()


def read_server_error(handle: ServerHandle) -> str:
    try:
        with open(handle.err_path) as f:
            return f.read().strip()
    except Exception:
        return ""


TURBO_CODE = textwrap.dedent(
    """
    import os

    os.environ["TURBO_DISABLE_CACHE"] = "1"
    os.environ["TURBO_DISABLE_DB_CACHE"] = "1"
    os.environ["TURBO_DISABLE_RATE_LIMITING"] = "1"
    os.environ["TURBO_THREAD_POOL_SIZE"] = "16"

    from turboapi import TurboAPI

    app = TurboAPI()
    app.configure_db("{db_url}", pool_size=16)

    @app.db_get("/users/{{user_id}}", table="users", pk="id", columns=["id", "name", "email", "age"])
    def get_user():
        pass

    @app.db_query(
        "GET",
        "/users",
        sql="SELECT id, name, email, age FROM users WHERE age > $1 ORDER BY id LIMIT 20",
        params=["age_min"],
    )
    def list_users():
        pass

    @app.db_query(
        "GET",
        "/search",
        sql="SELECT id, name, email FROM users WHERE name ILIKE $1 LIMIT 10",
        params=["q"],
    )
    def search():
        pass

    @app.get("/health")
    def health():
        return {{"status": "ok"}}

    app.run(host="127.0.0.1", port={port})
    """
)


FASTAPI_ASYNCPG_CODE = textwrap.dedent(
    """
    import asyncpg
    import uvicorn
    from contextlib import asynccontextmanager
    from fastapi import FastAPI

    DB_URL = "{db_url}".replace("postgresql://", "postgres://")
    pool = None

    @asynccontextmanager
    async def lifespan(app):
        global pool
        pool = await asyncpg.create_pool(DB_URL, min_size=16, max_size=16)
        yield
        await pool.close()

    app = FastAPI(lifespan=lifespan)

    @app.get("/users/{{user_id}}")
    async def get_user(user_id: int):
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, name, email, age FROM users WHERE id = $1",
                user_id,
            )
        return dict(row) if row else {{"error": "not found"}}

    @app.get("/users")
    async def list_users(age_min: int = 20):
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, name, email, age FROM users WHERE age > $1 ORDER BY id LIMIT 20",
                age_min,
            )
        return [dict(row) for row in rows]

    @app.get("/search")
    async def search(q: str):
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, name, email FROM users WHERE name ILIKE $1 LIMIT 10",
                q,
            )
        return [dict(row) for row in rows]

    @app.get("/health")
    async def health():
        return {{"status": "ok"}}

    uvicorn.run(app, host="127.0.0.1", port={port}, log_level="error", access_log=False)
    """
)


FASTAPI_SQLALCHEMY_CODE = textwrap.dedent(
    """
    import uvicorn
    from fastapi import FastAPI
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    engine = create_engine("{db_url}", pool_size=16)
    app = FastAPI()

    @app.get("/users/{{user_id}}")
    def get_user(user_id: int):
        with Session(engine) as session:
            row = session.execute(
                text("SELECT id, name, email, age FROM users WHERE id = :id"),
                {{"id": user_id}},
            ).fetchone()
        return dict(row._mapping) if row else {{"error": "not found"}}

    @app.get("/users")
    def list_users(age_min: int = 20):
        with Session(engine) as session:
            rows = session.execute(
                text("SELECT id, name, email, age FROM users WHERE age > :age_min ORDER BY id LIMIT 20"),
                {{"age_min": age_min}},
            ).fetchall()
        return [dict(row._mapping) for row in rows]

    @app.get("/search")
    def search(q: str):
        with Session(engine) as session:
            rows = session.execute(
                text("SELECT id, name, email FROM users WHERE name ILIKE :q LIMIT 10"),
                {{"q": q}},
            ).fetchall()
        return [dict(row._mapping) for row in rows]

    @app.get("/health")
    def health():
        return {{"status": "ok"}}

    uvicorn.run(app, host="127.0.0.1", port={port}, log_level="error", access_log=False)
    """
)


def main() -> int:
    print("=" * 78, flush=True)
    print("TurboAPI + pg.zig vs FastAPI + asyncpg / SQLAlchemy", flush=True)
    print("=" * 78, flush=True)
    print(f"Postgres: {DB_URL}", flush=True)
    print(f"wrk: -t{WRK_THREADS} -c{WRK_CONNECTIONS} -d{WRK_DURATION}", flush=True)
    print("All servers expose the same HTTP routes. TurboAPI cache is OFF.", flush=True)
    print(flush=True)

    servers = [
        ("TurboAPI + pg.zig", TURBO_CODE),
        ("FastAPI + asyncpg", FASTAPI_ASYNCPG_CODE),
        ("FastAPI + SQLAlchemy", FASTAPI_SQLALCHEMY_CODE),
    ]

    handles: list[ServerHandle] = []
    try:
        for name, code in servers:
            print(f"Starting {name}...", end=" ", flush=True)
            handle = start_server(name, code)
            if not wait_for(handle.port):
                print("FAILED", flush=True)
                err = read_server_error(handle)
                if err:
                    print(err, flush=True)
                return 1
            print(f"OK (port {handle.port})", flush=True)
            warmup(handle.port)
            handles.append(handle)

        print(flush=True)
        tests = [
            ("GET /health", "health", lambda port: run_wrk(f"http://127.0.0.1:{port}/health", "GET /health")),
            (
                "GET /users/{id} (varying 1000 IDs)",
                "by_id",
                lambda port: run_wrk_lua(
                    f"http://127.0.0.1:{port}/users/1",
                    "benchmarks/postgres/varying_ids.lua",
                    "GET /users/{id} (varying 1000 IDs)",
                ),
            ),
            (
                "GET /users?age_min=20",
                "list",
                lambda port: run_wrk(
                    f"http://127.0.0.1:{port}/users?age_min=20",
                    "GET /users?age_min=20",
                ),
            ),
            (
                "GET /search?q=user_42%%",
                "search",
                lambda port: run_wrk(
                    f"http://127.0.0.1:{port}/search?q=user_42%25",
                    "GET /search?q=user_42%",
                ),
            ),
        ]

        results: dict[str, dict[str, float]] = {key: {} for _, key, _ in tests}

        for label, key, runner in tests:
            print(f"=== {label} ===", flush=True)
            for handle in handles:
                rps, _ = runner(handle.port)
                results[key][handle.name] = rps
            print(flush=True)

        print("=" * 78, flush=True)
        print("SUMMARY", flush=True)
        print("=" * 78, flush=True)
        header = "{:<30} {:>16} {:>18} {:>22}"
        print(
            header.format(
                "Test",
                "TurboAPI+pg.zig",
                "FastAPI+asyncpg",
                "FastAPI+SQLAlchemy",
            ),
            flush=True,
        )
        print("-" * 90, flush=True)
        row = "{:<30} {:>16,.0f} {:>18,.0f} {:>22,.0f}"
        print(
            row.format(
                "GET /health",
                results["health"]["TurboAPI + pg.zig"],
                results["health"]["FastAPI + asyncpg"],
                results["health"]["FastAPI + SQLAlchemy"],
            ),
            flush=True,
        )
        print(
            row.format(
                "GET /users/{id}",
                results["by_id"]["TurboAPI + pg.zig"],
                results["by_id"]["FastAPI + asyncpg"],
                results["by_id"]["FastAPI + SQLAlchemy"],
            ),
            flush=True,
        )
        print(
            row.format(
                "GET /users",
                results["list"]["TurboAPI + pg.zig"],
                results["list"]["FastAPI + asyncpg"],
                results["list"]["FastAPI + SQLAlchemy"],
            ),
            flush=True,
        )
        print(
            row.format(
                "GET /search",
                results["search"]["TurboAPI + pg.zig"],
                results["search"]["FastAPI + asyncpg"],
                results["search"]["FastAPI + SQLAlchemy"],
            ),
            flush=True,
        )
        print("-" * 90, flush=True)
        return 0
    finally:
        for handle in handles:
            stop_server(handle)


if __name__ == "__main__":
    raise SystemExit(main())
