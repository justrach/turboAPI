"""Quick smoke test — verifies turboapi-core extraction didn't break anything."""

from turboapi import TurboAPI

app = TurboAPI(title="Core Extraction Test")


@app.get("/")
def root():
    return {"status": "ok", "message": "turboapi-core extraction works!"}


@app.get("/hello/{name}")
def hello(name: str):
    return {"hello": name}


@app.get("/add/{a}/{b}")
def add(a: int, b: int):
    return {"result": a + b}


@app.get("/search")
def search(q: str = "default", page: int = 1):
    return {"query": q, "page": page}


if __name__ == "__main__":
    from turboapi.testclient import TestClient

    client = TestClient(app)

    print("Testing routes via turboapi-core radix trie router...")

    r = client.get("/")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    print(f"  GET /              -> {r.status_code} {r.json()}")

    r = client.get("/hello/rach")
    assert r.status_code == 200 and r.json()["hello"] == "rach"
    print(f"  GET /hello/rach    -> {r.status_code} {r.json()}")

    r = client.get("/add/3/4")
    assert r.status_code == 200 and r.json()["result"] == 7
    print(f"  GET /add/3/4       -> {r.status_code} {r.json()}")

    r = client.get("/search?q=zig&page=2")
    assert r.status_code == 200 and r.json()["query"] == "zig" and r.json()["page"] == 2
    print(f"  GET /search?q=zig  -> {r.status_code} {r.json()}")

    print("\nAll routes working! turboapi-core extraction is clean.")
