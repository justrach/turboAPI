"""
TurboPG — Zig-native Postgres client for Python.

Zero-overhead database operations powered by pg.zig. Works standalone
or as TurboAPI's built-in DB layer.

Usage:
    from turbopg import Database

    db = Database("postgres://user:pass@localhost/mydb", pool_size=16)

    # Simple queries
    user = db.query_one("SELECT * FROM users WHERE id = $1", [42])
    users = db.query("SELECT * FROM users WHERE age > $1 LIMIT $2", [18, 10])

    # Execute (INSERT/UPDATE/DELETE)
    db.execute("INSERT INTO users (name, email) VALUES ($1, $2)", ["Alice", "a@b.com"])

    # With TurboAPI (zero-Python DB routes)
    from turboapi import TurboAPI
    app = TurboAPI()
    app.configure_db("postgres://...", pool_size=16)

    @app.db_get("/users/{user_id}", table="users", pk="id")
    def get_user(): pass
"""

__version__ = "0.1.1"

from .client import Database

__all__ = ["Database", "__version__"]
