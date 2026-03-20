"""Test complex database operations — real-world patterns people actually use."""
from dhi import BaseModel, Field
from turboapi import TurboAPI

app = TurboAPI()
app.configure_db("postgres://turbo:turbo@127.0.0.1:5432/turbotest", pool_size=16)


# ── Simple CRUD (auto-generated) ──────────────────────────────────────────────

class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str
    age: int = Field(gt=0, le=150)


@app.db_get("/users/{user_id}", table="users", pk="id")
def get_user():
    pass


@app.db_list("/users", table="users")
def list_users():
    pass


@app.db_post("/users", table="users", model=UserCreate)
def create_user():
    pass


# ── JOIN: user with their post count and total spend ──────────────────────────

@app.db_query("GET", "/users/{user_id}/stats", sql="""
    SELECT u.id, u.name, u.email,
           count(DISTINCT p.id) AS post_count,
           count(DISTINCT o.id) AS order_count,
           COALESCE(sum(o.total), 0) AS total_spent
    FROM users u
    LEFT JOIN posts p ON u.id = p.user_id
    LEFT JOIN orders o ON u.id = o.user_id
    WHERE u.id = $1
    GROUP BY u.id, u.name, u.email
""", params=["user_id"], single=True)
def user_stats():
    pass


# ── Full-text search ─────────────────────────────────────────────────────────

@app.db_query("GET", "/search", sql="""
    SELECT p.id, p.title, u.name AS author,
           ts_rank(p.tsv, plainto_tsquery('english', $1)) AS rank
    FROM posts p
    JOIN users u ON p.user_id = u.id
    WHERE p.tsv @@ plainto_tsquery('english', $1)
    ORDER BY rank DESC
    LIMIT 10
""", params=["q"])
def search():
    pass


# ── JSONB: filter by metadata ────────────────────────────────────────────────

@app.db_query("GET", "/admins", sql="""
    SELECT id, name, email, metadata->>'plan' AS plan
    FROM users
    WHERE metadata @> '{"role": "admin", "active": true}'
""")
def active_admins():
    pass


# ── Aggregation: revenue by status ───────────────────────────────────────────

@app.db_query("GET", "/revenue", sql="""
    SELECT status, count(*) AS order_count, sum(total) AS revenue
    FROM orders
    GROUP BY status
    ORDER BY revenue DESC
""")
def revenue_by_status():
    pass


# ── Subquery: users who spent more than average ──────────────────────────────

@app.db_query("GET", "/big-spenders", sql="""
    SELECT u.id, u.name, sub.total_spent
    FROM users u
    JOIN (
        SELECT user_id, sum(total) AS total_spent
        FROM orders
        WHERE status = 'completed'
        GROUP BY user_id
        HAVING sum(total) > (SELECT avg(total) FROM orders WHERE status = 'completed')
    ) sub ON u.id = sub.user_id
    ORDER BY sub.total_spent DESC
""")
def big_spenders():
    pass


# ── Array: posts by tag ──────────────────────────────────────────────────────

@app.db_query("GET", "/posts/by-tag", sql="""
    SELECT id, title, tags
    FROM posts
    WHERE $1 = ANY(tags)
    ORDER BY created_at DESC
""", params=["tag"])
def posts_by_tag():
    pass


# ── Health check (pure Python, no DB) ────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)
