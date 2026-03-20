"""Test: parameterized routes with varying IDs + auth via Depends."""
from typing import Annotated

from turboapi import TurboAPI
from turboapi.security import Depends

app = TurboAPI()
app.configure_db("postgres://turbo:turbo@127.0.0.1:5432/turbotest", pool_size=16)


# ── Auth dependency ──────────────────────────────────────────────────────────

def get_api_key(headers: dict = None):
    """Simulate API key validation."""
    return {"authenticated": True, "user": "test_user"}


ApiKey = Annotated[dict, Depends(get_api_key)]


# ── DB routes (Zig-native, no Python) ────────────────────────────────────────

@app.db_get("/users/{user_id}", table="users", pk="id")
def get_user():
    pass


@app.db_list("/users", table="users")
def list_users():
    pass


@app.db_query(
    "GET",
    "/users/{user_id}/posts",
    sql="SELECT id, title, body FROM posts WHERE user_id = $1 LIMIT 10",
    params=["user_id"],
)
def user_posts():
    pass


# ── Python routes with auth (uses Depends, goes through enhanced path) ───────

@app.get("/me")
def get_me(auth: ApiKey):
    return {"user": auth["user"], "authenticated": auth["authenticated"]}


@app.get("/protected/{item_id}")
def get_protected_item(item_id: int, auth: ApiKey):
    return {"item_id": item_id, "user": auth["user"]}


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)
