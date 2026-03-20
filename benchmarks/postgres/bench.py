"""
asyncpg vs TurboAPI+pg.zig -- head-to-head benchmark.

Runs inside Docker alongside Postgres 18. Fully reproducible.

Tests 4 configurations:
  1. asyncpg         -- raw Python, concurrent (asyncio.gather, pool=16)
  2. Turbo cached    -- Zig response cache enabled (repeat requests hit cache)
  3. Turbo no-cache  -- varying IDs via wrk lua script (every request hits Postgres)
  4. Turbo raw SQL   -- custom SQL queries, ORDER BY random() to bust cache

Usage:
  cd benchmarks/postgres
  docker compose up --build
"""

import asyncio
import os
import re
import socket
import subprocess
import threading
import time

CONN = os.environ.get("BENCH_PG_URL", "postgresql://bench:bench@localhost:5432/bench")
WRK_DURATION = os.environ.get("BENCH_DURATION", "10s")
WRK_THREADS = 4
WRK_CONNECTIONS = 100
N_ASYNC = 10_000


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def parse_wrk(output):
    rps = 0
    lat = ""
    for line in output.splitlines():
        if "Requests/sec" in line:
            m = re.search(r"Requests/sec:\s*([\d.]+)", line)
            if m:
                rps = float(m.group(1))
        if "Latency" in line and "Distribution" not in line:
            lat = line.strip()
    return rps, lat


def run_wrk(url, label):
    r = subprocess.run(
        ["wrk", f"-t{WRK_THREADS}", f"-c{WRK_CONNECTIONS}", f"-d{WRK_DURATION}", url],
        capture_output=True, text=True,
    )
    rps, lat = parse_wrk(r.stdout)
    print(f"  {label}: {rps:,.0f} req/s  |  {lat}", flush=True)
    return rps


def run_wrk_lua(url, lua_path, label):
    r = subprocess.run(
        ["wrk", f"-t{WRK_THREADS}", f"-c{WRK_CONNECTIONS}", f"-d{WRK_DURATION}", "-s", lua_path, url],
        capture_output=True, text=True,
    )
    rps, lat = parse_wrk(r.stdout)
    print(f"  {label}: {rps:,.0f} req/s  |  {lat}", flush=True)
    return rps


# ---------------------------------------------------------------------------
# 1. asyncpg
# ---------------------------------------------------------------------------
def bench_asyncpg():
    print("\n=== 1. asyncpg (concurrent, pool=16) ===", flush=True)

    async def run():
        import asyncpg
        conn_str = CONN.replace("postgresql://", "postgres://")
        pool = await asyncpg.create_pool(conn_str, min_size=16, max_size=16)

        # warmup
        for i in range(200):
            await pool.fetchrow("SELECT * FROM users WHERE id = $1", (i % 1000) + 1)

        # SELECT by ID
        start = time.perf_counter()
        tasks = [pool.fetchrow("SELECT * FROM users WHERE id = $1", (i % 1000) + 1) for i in range(N_ASYNC)]
        await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - start
        rps_id = N_ASYNC / elapsed
        print(f"  SELECT by ID:   {rps_id:,.0f} queries/sec  ({elapsed:.2f}s for {N_ASYNC})", flush=True)

        # SELECT list
        start2 = time.perf_counter()
        tasks2 = [pool.fetch("SELECT * FROM users WHERE age > $1 LIMIT 20", 20 + (i % 30)) for i in range(N_ASYNC)]
        await asyncio.gather(*tasks2)
        elapsed2 = time.perf_counter() - start2
        rps_list = N_ASYNC / elapsed2
        print(f"  SELECT list:    {rps_list:,.0f} queries/sec  ({elapsed2:.2f}s for {N_ASYNC})", flush=True)

        # Raw ILIKE
        start3 = time.perf_counter()
        tasks3 = [
            pool.fetch("SELECT id, name, email FROM users WHERE name ILIKE $1 LIMIT 10", f"user_{(i%500)+1}%")
            for i in range(N_ASYNC)
        ]
        await asyncio.gather(*tasks3)
        elapsed3 = time.perf_counter() - start3
        rps_raw = N_ASYNC / elapsed3
        print(f"  Raw ILIKE:      {rps_raw:,.0f} queries/sec  ({elapsed3:.2f}s for {N_ASYNC})", flush=True)

        await pool.close()
        return rps_id, rps_list, rps_raw

    return asyncio.run(run())


# ---------------------------------------------------------------------------
# 2-4. TurboAPI+pg.zig
# ---------------------------------------------------------------------------
def start_turbo_app(routes_fn):
    from turboapi import TurboAPI
    app = TurboAPI()
    app.configure_db(CONN, pool_size=16)
    routes_fn(app)
    port = free_port()
    # Store server thread so we can reference it
    server_thread = threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port), daemon=True)
    server_thread.start()
    time.sleep(3)
    # warmup: hit enough unique IDs to prime all 16 pool connections
    import requests
    for i in range(200):
        requests.get(f"http://127.0.0.1:{port}/users/{(i % 1000) + 1}", timeout=5)
    time.sleep(1)
    return port
def routes_cached(app):
    @app.db_get("/users/{user_id}", table="users", pk="id")
    def get_user():
        pass

    @app.db_query("GET", "/users", sql="SELECT id, name, email, age FROM users LIMIT 20")
    def list_users():
        pass


def routes_nocache(app):
    @app.db_get("/users/{user_id}", table="users", pk="id")
    def get_user():
        pass

    @app.db_query("GET", "/users", sql="SELECT id, name, email, age FROM users ORDER BY random() LIMIT 20")
    def list_users():
        pass


def routes_raw(app):
    @app.db_get("/users/{user_id}", table="users", pk="id")
    def get_user():
        pass

    @app.db_query("GET", "/users", sql="SELECT id, name, email, age FROM users ORDER BY random() LIMIT 20")
    def list_users():
        pass

    @app.db_query("GET", "/search", sql="SELECT id, name, email FROM users WHERE name ILIKE $1 LIMIT 10", params=["q"])
    def search():
        pass


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    import json as json_mod

    results_file = "/tmp/bench_results.json"

    # Check if we're running a sub-test or the orchestrator
    mode = os.environ.get("BENCH_MODE", "orchestrate")

    if mode == "asyncpg":
        apg_id, apg_list, apg_raw = bench_asyncpg()
        with open(results_file, "w") as f:
            json_mod.dump({"apg_id": apg_id, "apg_list": apg_list, "apg_raw": apg_raw}, f)
        os._exit(0)

    elif mode == "turbo_cached":
        port = start_turbo_app(routes_cached)
        print("\n=== 2. TurboAPI+pg.zig CACHED ===", flush=True)
        rps_id = run_wrk(f"http://127.0.0.1:{port}/users/1", "SELECT by ID (cached)")
        rps_list = run_wrk(f"http://127.0.0.1:{port}/users", "SELECT list (cached)")
        with open(results_file, "w") as f:
            json_mod.dump({"rps_id": rps_id, "rps_list": rps_list}, f)
        os._exit(0)

    elif mode == "turbo_nocache":
        port = start_turbo_app(routes_nocache)
        print("\n=== 3. TurboAPI+pg.zig NO CACHE (varying IDs) ===", flush=True)
        rps_id = run_wrk_lua(
            f"http://127.0.0.1:{port}/users/1", "/app/varying_ids.lua",
            "SELECT by ID (varying)",
        )
        rps_list = run_wrk(f"http://127.0.0.1:{port}/users", "SELECT list (random)")
        with open(results_file, "w") as f:
            json_mod.dump({"rps_id": rps_id, "rps_list": rps_list}, f)
        os._exit(0)

    elif mode == "turbo_raw":
        port = start_turbo_app(routes_raw)
        print("\n=== 4. TurboAPI+pg.zig RAW QUERY ===", flush=True)
        rps_id = run_wrk_lua(
            f"http://127.0.0.1:{port}/users/1", "/app/varying_ids.lua",
            "SELECT by ID (varying)",
        )
        rps_list = run_wrk(f"http://127.0.0.1:{port}/users", "SELECT list (random)")
        rps_search = run_wrk(f"http://127.0.0.1:{port}/search?q=user_42%25", "Raw ILIKE search")
        with open(results_file, "w") as f:
            json_mod.dump({"rps_id": rps_id, "rps_list": rps_list, "rps_search": rps_search}, f)
        os._exit(0)

    # --- Orchestrator: run each test as a separate process ---
    print("=" * 70, flush=True)
    print("asyncpg vs TurboAPI+pg.zig -- Head-to-Head Benchmark", flush=True)
    print("=" * 70, flush=True)
    print(f"Postgres: {CONN}", flush=True)
    print(f"wrk: -t{WRK_THREADS} -c{WRK_CONNECTIONS} -d{WRK_DURATION}", flush=True)
    print(f"asyncpg: {N_ASYNC} queries via asyncio.gather", flush=True)
    print("Each test runs in its own process (no resource contention)", flush=True)

    import sys
    script = os.path.abspath(__file__)
    env_base = dict(os.environ)

    def run_sub(mode_name):
        env = dict(env_base)
        env["BENCH_MODE"] = mode_name
        r = subprocess.run(
            [sys.executable, script],
            env=env, capture_output=False, timeout=300,
        )
        if r.returncode != 0:
            print(f"  {mode_name} failed (exit {r.returncode})", flush=True)
            return {}
        try:
            with open(results_file) as f:
                return json_mod.load(f)
        except Exception:
            return {}

    r1 = run_sub("asyncpg")
    r2 = run_sub("turbo_cached")
    r3 = run_sub("turbo_nocache")
    r4 = run_sub("turbo_raw")

    apg_id = r1.get("apg_id", 0)
    apg_list = r1.get("apg_list", 0)
    apg_raw = r1.get("apg_raw", 0)
    rps_cached_id = r2.get("rps_id", 0)
    rps_cached_list = r2.get("rps_list", 0)
    rps_nc_id = r3.get("rps_id", 0)
    rps_nc_list = r3.get("rps_list", 0)
    rps_raw_id = r4.get("rps_id", 0)
    rps_raw_list = r4.get("rps_list", 0)
    rps_raw_search = r4.get("rps_search", 0)

    print("\n" + "=" * 70, flush=True)
    print("SUMMARY", flush=True)
    print("=" * 70, flush=True)
    fmt = "{:<35} {:>12} {:>14} {:>14} {:>14}"
    print(fmt.format("Test", "asyncpg", "Turbo cached", "Turbo no-cache", "Turbo raw"), flush=True)
    print("-" * 89, flush=True)
    print(fmt.format(
        "SELECT by ID (q/s)",
        f"{apg_id:,.0f}", f"{rps_cached_id:,.0f}", f"{rps_nc_id:,.0f}", f"{rps_raw_id:,.0f}",
    ), flush=True)
    print(fmt.format(
        "SELECT list (q/s)",
        f"{apg_list:,.0f}", f"{rps_cached_list:,.0f}", f"{rps_nc_list:,.0f}", f"{rps_raw_list:,.0f}",
    ), flush=True)
    print(fmt.format(
        "Raw ILIKE (q/s)",
        f"{apg_raw:,.0f}", "n/a", "n/a", f"{rps_raw_search:,.0f}",
    ), flush=True)
    print("-" * 89, flush=True)

    if apg_id > 0:
        print("\nMultipliers vs asyncpg:", flush=True)
        if rps_cached_id:
            print(f"  Cached by-ID:     {rps_cached_id/apg_id:.1f}x", flush=True)
        if rps_nc_id:
            print(f"  No-cache by-ID:   {rps_nc_id/apg_id:.1f}x", flush=True)
        if rps_cached_list and apg_list:
            print(f"  Cached list:      {rps_cached_list/apg_list:.1f}x", flush=True)
        if rps_nc_list and apg_list:
            print(f"  No-cache list:    {rps_nc_list/apg_list:.1f}x", flush=True)
        if rps_raw_search and apg_raw:
            print(f"  Raw ILIKE:        {rps_raw_search/apg_raw:.1f}x", flush=True)

    print("\nDone.", flush=True)
    os._exit(0)
if __name__ == "__main__":
    main()
