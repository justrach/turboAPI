#!/usr/bin/env python3
"""
Full comparison: TurboAPI+pg.zig vs FastAPI+SQLAlchemy
Tests every real-world pattern people actually use.
"""
import re
import signal
import subprocess
import sys
import time
import urllib.request

DB_URL = "postgres://turbo:turbo@127.0.0.1:5432/turbotest"
TURBO_PORT = 8100
FASTAPI_PORT = 8200
WRK_T = 2
WRK_C = 50
WRK_D = "5s"
procs = []


def start_turbo():
    code = f"""
import sys; sys.path.insert(0, 'python')
from turboapi import TurboAPI
app = TurboAPI()
app.configure_db('{DB_URL}', pool_size=16)

# 1. Simple PK lookup
@app.db_get('/users/{{user_id}}', table='users', pk='id')
def get_user(): pass

# 2. Paginated list
@app.db_list('/users', table='users')
def list_users(): pass

# 3. Multi-table JOIN + aggregation
@app.db_query('GET', '/users/{{user_id}}/dashboard', sql='''
    SELECT u.name, u.email,
           count(DISTINCT p.id) AS posts, count(DISTINCT o.id) AS orders,
           COALESCE(sum(o.total), 0) AS revenue
    FROM users u LEFT JOIN posts p ON u.id = p.user_id
    LEFT JOIN orders o ON u.id = o.user_id WHERE u.id = $1
    GROUP BY u.name, u.email
''', params=['user_id'], single=True)
def dashboard(): pass

# 4. Full-text search
@app.db_query('GET', '/search', sql='''
    SELECT p.id, p.title, u.name AS author,
           ts_rank(p.tsv, plainto_tsquery('english', $1)) AS rank
    FROM posts p JOIN users u ON p.user_id = u.id
    WHERE p.tsv @@ plainto_tsquery('english', $1) ORDER BY rank DESC LIMIT 10
''', params=['q'])
def search(): pass

# 5. JSONB filter
@app.db_query('GET', '/admins', sql='''
    SELECT id, name, email, metadata->>'plan' AS plan
    FROM users WHERE metadata @> '{{"role": "admin", "active": true}}'
''')
def admins(): pass

# 6. GROUP BY aggregation
@app.db_query('GET', '/order-stats', sql='''
    SELECT status, count(*) AS cnt, sum(total) AS revenue,
           round(avg(total)::numeric, 2) AS avg_order
    FROM orders GROUP BY status ORDER BY revenue DESC
''')
def order_stats(): pass

# 7. Subquery: top spenders
@app.db_query('GET', '/top-spenders', sql='''
    SELECT u.id, u.name, sub.total_spent, sub.order_count
    FROM users u JOIN (
        SELECT user_id, sum(total) AS total_spent, count(*) AS order_count
        FROM orders WHERE status = 'completed' GROUP BY user_id
        HAVING sum(total) > 100 ORDER BY total_spent DESC LIMIT 10
    ) sub ON u.id = sub.user_id
''')
def top_spenders(): pass

# 8. Array column query
@app.db_query('GET', '/posts/tagged', sql='''
    SELECT id, title, tags, views FROM posts
    WHERE $1 = ANY(tags) ORDER BY views DESC LIMIT 10
''', params=['tag'])
def tagged(): pass

# 9. Insert
@app.db_post('/users', table='users', model=None)
def create_user(): pass

# 10. Health (baseline)
@app.get('/health')
def health():
    return {{'status': 'ok'}}

app.run(host='127.0.0.1', port={TURBO_PORT})
"""
    p = subprocess.Popen([sys.executable, "-c", code],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)


def start_fastapi():
    code = f"""
import uvicorn
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

DB = '{DB_URL}'.replace('postgres://', 'postgresql://')
engine = create_engine(DB, pool_size=16)
app = FastAPI()

@app.get('/users/{{user_id}}')
def get_user(user_id: int):
    with Session(engine) as s:
        r = s.execute(text('SELECT id,name,email,age FROM users WHERE id=:id'), {{'id': user_id}}).fetchone()
        return dict(r._mapping) if r else {{'error': 'not found'}}

@app.get('/users')
def list_users(limit: int = 50, offset: int = 0):
    with Session(engine) as s:
        rows = s.execute(text('SELECT id,name,email,age FROM users LIMIT :l OFFSET :o'), {{'l': limit, 'o': offset}}).fetchall()
        return [dict(r._mapping) for r in rows]

@app.get('/users/{{user_id}}/dashboard')
def dashboard(user_id: int):
    with Session(engine) as s:
        r = s.execute(text('''
            SELECT u.name, u.email, count(DISTINCT p.id) AS posts, count(DISTINCT o.id) AS orders,
                   COALESCE(sum(o.total), 0) AS revenue
            FROM users u LEFT JOIN posts p ON u.id = p.user_id LEFT JOIN orders o ON u.id = o.user_id
            WHERE u.id = :id GROUP BY u.name, u.email
        '''), {{'id': user_id}}).fetchone()
        return dict(r._mapping) if r else {{}}

@app.get('/search')
def search(q: str):
    with Session(engine) as s:
        rows = s.execute(text('''
            SELECT p.id, p.title, u.name AS author,
                   ts_rank(p.tsv, plainto_tsquery('english', :q)) AS rank
            FROM posts p JOIN users u ON p.user_id = u.id
            WHERE p.tsv @@ plainto_tsquery('english', :q) ORDER BY rank DESC LIMIT 10
        '''), {{'q': q}}).fetchall()
        return [dict(r._mapping) for r in rows]

@app.get('/admins')
def admins():
    with Session(engine) as s:
        rows = s.execute(text('''
            SELECT id, name, email, metadata->>'plan' AS plan FROM users
            WHERE metadata @> '{{"role": "admin", "active": true}}'
        ''')).fetchall()
        return [dict(r._mapping) for r in rows]

@app.get('/order-stats')
def order_stats():
    with Session(engine) as s:
        rows = s.execute(text('''
            SELECT status, count(*) AS cnt, sum(total) AS revenue,
                   round(avg(total)::numeric, 2) AS avg_order
            FROM orders GROUP BY status ORDER BY revenue DESC
        ''')).fetchall()
        return [dict(r._mapping) for r in rows]

@app.get('/top-spenders')
def top_spenders():
    with Session(engine) as s:
        rows = s.execute(text('''
            SELECT u.id, u.name, sub.total_spent, sub.order_count FROM users u JOIN (
                SELECT user_id, sum(total) AS total_spent, count(*) AS order_count
                FROM orders WHERE status = 'completed' GROUP BY user_id
                HAVING sum(total) > 100 ORDER BY total_spent DESC LIMIT 10
            ) sub ON u.id = sub.user_id
        ''')).fetchall()
        return [dict(r._mapping) for r in rows]

@app.get('/posts/tagged')
def tagged(tag: str):
    with Session(engine) as s:
        rows = s.execute(text('''
            SELECT id, title, tags, views FROM posts
            WHERE :tag = ANY(tags) ORDER BY views DESC LIMIT 10
        '''), {{'tag': tag}}).fetchall()
        return [dict(r._mapping) for r in rows]

@app.get('/health')
def health():
    return {{'status': 'ok'}}

uvicorn.run(app, host='127.0.0.1', port={FASTAPI_PORT}, log_level='error')
"""
    p = subprocess.Popen([sys.executable, "-c", code],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)


def wait_for(port, timeout=15):
    for _ in range(timeout * 10):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def wrk(port, path):
    try:
        r = subprocess.run(
            ["wrk", f"-t{WRK_T}", f"-c{WRK_C}", f"-d{WRK_D}",
             f"http://127.0.0.1:{port}{path}"],
            capture_output=True, text=True, timeout=30)
        rps = 0.0
        lat = ""
        for line in r.stdout.splitlines():
            if "Requests/sec:" in line:
                m = re.search(r"Requests/sec:\s*([\d.]+)", line)
                if m:
                    rps = float(m.group(1))
            if "Latency" in line and "Distribution" not in line:
                lat = line.strip()
        return rps, lat
    except Exception as e:
        return 0, str(e)


def main():
    print("\n" + "=" * 80)
    print("  TurboAPI+pg.zig vs FastAPI+SQLAlchemy — Full Comparison (Postgres 18)")
    print("=" * 80)
    print(f"  wrk: {WRK_T}t, {WRK_C}c, {WRK_D} | Python {sys.version.split()[0]}")

    print("\n  Starting TurboAPI...", end=" ", flush=True)
    start_turbo()
    print("OK" if wait_for(TURBO_PORT) else "FAIL")

    print("  Starting FastAPI...", end=" ", flush=True)
    start_fastapi()
    print("OK" if wait_for(FASTAPI_PORT) else "FAIL")

    # Warm caches
    for path in ["/users/1", "/users?limit=10", "/users/1/dashboard",
                 "/search?q=lorem", "/admins", "/order-stats",
                 "/top-spenders", "/posts/tagged?tag=tag1", "/health"]:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{TURBO_PORT}{path}", timeout=2)
        except Exception:
            pass

    tests = [
        ("health",       "/health",                    "Baseline (no DB)"),
        ("pk_lookup",    "/users/1",                   "SELECT by PK"),
        ("list_10",      "/users?limit=10",            "Paginated list (10 rows)"),
        ("join_agg",     "/users/1/dashboard",         "JOIN 3 tables + aggregation"),
        ("fts",          "/search?q=lorem",            "Full-text search"),
        ("jsonb",        "/admins",                    "JSONB filter"),
        ("group_by",     "/order-stats",               "GROUP BY + sum/avg"),
        ("subquery",     "/top-spenders",              "Subquery + HAVING"),
        ("array",        "/posts/tagged?tag=tag1",     "Array contains"),
    ]

    print(f"\n  {'Test':<25} {'TurboAPI':>12} {'FastAPI':>12} {'Speedup':>10}")
    print("  " + "-" * 65)

    results = {}
    for key, path, label in tests:
        t_rps, t_lat = wrk(TURBO_PORT, path)
        f_rps, f_lat = wrk(FASTAPI_PORT, path)
        speedup = f"{t_rps / f_rps:.1f}x" if f_rps > 0 else "N/A"
        print(f"  {label:<25} {t_rps:>10.0f}/s {f_rps:>10.0f}/s {speedup:>10}")
        results[key] = {"turbo": t_rps, "fastapi": f_rps}

    print("  " + "-" * 65)
    print("\n  Latency samples (last test each):")
    for key, path, label in tests[:4]:
        _, t_lat = wrk(TURBO_PORT, path)
        _, f_lat = wrk(FASTAPI_PORT, path)
        print(f"  {label:<25} T: {t_lat}")
        print(f"  {'':25} F: {f_lat}")

    print("\n" + "=" * 80)

    for p in procs:
        p.send_signal(signal.SIGTERM)
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()


if __name__ == "__main__":
    main()
