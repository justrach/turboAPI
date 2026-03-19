#!/usr/bin/env python3
"""
Benchmark: TurboAPI pg.zig (zero-Python) vs SQLAlchemy (Python ORM)

Usage:
    # Terminal 1: start TurboAPI with pg.zig
    python examples/db_benchmark.py serve-turbo

    # Terminal 2: start FastAPI with SQLAlchemy
    python examples/db_benchmark.py serve-fastapi

    # Terminal 3: run benchmark
    python examples/db_benchmark.py bench
"""

import subprocess
import sys

DB_URL = "postgres://turbo:turbo@127.0.0.1:5432/turbotest"
TURBO_PORT = 8000
FASTAPI_PORT = 9000


def serve_turbo():
    """TurboAPI with Zig-native pg.zig CRUD."""
    from dhi import BaseModel, Field
    from turboapi import TurboAPI

    app = TurboAPI()
    app.configure_db(DB_URL, pool_size=16)

    class User(BaseModel):
        name: str = Field(min_length=1, max_length=100)
        email: str
        age: int = Field(gt=0, le=150)

    @app.db_get("/users/{user_id}", table="users", pk="id")
    def get_user():
        pass

    @app.db_list("/users", table="users")
    def list_users():
        pass

    @app.db_post("/users", table="users", model=User)
    def create_user():
        pass

    @app.db_delete("/users/{user_id}", table="users", pk="id")
    def delete_user():
        pass

    # Also add a regular Python handler for comparison
    @app.get("/health")
    def health():
        return {"status": "ok"}

    print(f"\n  TurboAPI + pg.zig on port {TURBO_PORT}")
    app.run(host="127.0.0.1", port=TURBO_PORT)


def serve_fastapi():
    """FastAPI with SQLAlchemy for comparison."""
    try:
        import uvicorn
        from fastapi import FastAPI
        from pydantic import BaseModel
        from sqlalchemy import Column, Integer, String, create_engine, text
        from sqlalchemy.orm import Session, declarative_base
    except ImportError:
        print("Install deps: pip install fastapi uvicorn sqlalchemy psycopg2-binary")
        sys.exit(1)

    engine = create_engine(DB_URL.replace("postgres://", "postgresql://"), pool_size=16)
    Base = declarative_base()

    class UserModel(Base):
        __tablename__ = "users"
        id = Column(Integer, primary_key=True)
        name = Column(String)
        email = Column(String)
        age = Column(Integer)

    class UserSchema(BaseModel):
        name: str
        email: str
        age: int

    app = FastAPI()

    @app.get("/users/{user_id}")
    def get_user(user_id: int):
        with Session(engine) as s:
            row = s.execute(
                text("SELECT id, name, email, age FROM users WHERE id = :id"), {"id": user_id}
            ).fetchone()
            if not row:
                return {"error": "Not found"}
            return {"id": row[0], "name": row[1], "email": row[2], "age": row[3]}

    @app.get("/users")
    def list_users(limit: int = 50, offset: int = 0):
        with Session(engine) as s:
            rows = s.execute(
                text("SELECT id, name, email, age FROM users LIMIT :l OFFSET :o"),
                {"l": limit, "o": offset},
            ).fetchall()
            return [{"id": r[0], "name": r[1], "email": r[2], "age": r[3]} for r in rows]

    @app.post("/users")
    def create_user(user: UserSchema):
        with Session(engine) as s:
            result = s.execute(
                text("INSERT INTO users (name, email, age) VALUES (:n, :e, :a) RETURNING id"),
                {"n": user.name, "e": user.email, "a": user.age},
            )
            s.commit()
            return {"id": result.fetchone()[0], "created": True}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    print(f"\n  FastAPI + SQLAlchemy on port {FASTAPI_PORT}")
    uvicorn.run(app, host="127.0.0.1", port=FASTAPI_PORT, log_level="error")


def bench():
    """Run wrk benchmarks against both servers."""
    import json
    import urllib.request

    def check(port, path="/health"):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2)
            return True
        except Exception:
            return False

    turbo_up = check(TURBO_PORT)
    fastapi_up = check(FASTAPI_PORT)

    if not turbo_up and not fastapi_up:
        print("Neither server is running. Start them first.")
        sys.exit(1)

    print("\n" + "=" * 70)
    print("  TurboAPI (pg.zig) vs FastAPI (SQLAlchemy) — DB Benchmark")
    print("=" * 70)

    endpoints = [
        ("GET /users/1 (select by PK)", "/users/1"),
        ("GET /users (list)", "/users?limit=10"),
    ]

    for name, path in endpoints:
        print(f"\n  {name}")
        print("  " + "-" * 50)

        for label, port, up in [
            ("TurboAPI+pg.zig", TURBO_PORT, turbo_up),
            ("FastAPI+SQLAlchemy", FASTAPI_PORT, fastapi_up),
        ]:
            if not up:
                print(f"    {label:25s}  (not running)")
                continue

            # Quick correctness check
            try:
                resp = urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2)
                data = json.loads(resp.read())
                print(f"    {label:25s}  response: {json.dumps(data)[:80]}...")
            except Exception as e:
                print(f"    {label:25s}  ERROR: {e}")
                continue

            # wrk benchmark
            try:
                result = subprocess.run(
                    ["wrk", "-t2", "-c50", "-d5s", f"http://127.0.0.1:{port}{path}"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                for line in result.stdout.splitlines():
                    if "Requests/sec" in line or "Latency" in line:
                        print(f"    {label:25s}  {line.strip()}")
            except FileNotFoundError:
                print("    (wrk not installed — brew install wrk)")
                break

    print("\n" + "=" * 70)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python examples/db_benchmark.py [serve-turbo|serve-fastapi|bench]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "serve-turbo":
        serve_turbo()
    elif cmd == "serve-fastapi":
        serve_fastapi()
    elif cmd == "bench":
        bench()
    else:
        print(f"Unknown command: {cmd}")
