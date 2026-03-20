"""Benchmark: SIMD pg.zig serialization vs baseline."""
from turboapi import TurboAPI

app = TurboAPI()
app.configure_db("postgres://turbo:turbo@127.0.0.1:5432/turbotest", pool_size=16)

# Single row with text
@app.db_get("/articles/{article_id}", table="articles", pk="id")
def get_article():
    pass

# List with text (exercises JSON escaping)
@app.db_list("/articles", table="articles")
def list_articles():
    pass

# Custom query with array columns
@app.db_query("GET", "/by-category", sql="""
    SELECT id, title, author, tags FROM articles WHERE category = $1 LIMIT $2
""", params=["cat", "limit"])
def by_category():
    pass

@app.get("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)
