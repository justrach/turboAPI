"""TurboAPI benchmark server for wrk testing."""
import time
from turboapi import TurboAPI

app = TurboAPI(title="TurboAPI Benchmark")

@app.get("/")
def root():
    return {"message": "Hello TurboAPI", "timestamp": time.time()}

@app.get("/users/{user_id}")
def get_user(user_id: int):
    return {"user_id": user_id, "name": f"User {user_id}"}

@app.get("/search")
def search(q: str, limit: int = 10):
    return {"query": q, "limit": limit, "results": [f"item_{i}" for i in range(limit)]}

@app.post("/users")
def create_user(name: str, email: str):
    return {"name": name, "email": email, "created_at": time.time()}

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8001)
