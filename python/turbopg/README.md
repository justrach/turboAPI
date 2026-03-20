# TurboPG

Zig-native Postgres client for Python. Zero-overhead database operations powered by [pg.zig](https://github.com/justrach/pg.zig).

## Install

```bash
pip install turbopg
# With psycopg2 fallback:
pip install turbopg[psycopg2]
```

## Usage

```python
from turbopg import Database

db = Database("postgres://user:pass@localhost/mydb", pool_size=16)

# Query rows
users = db.query("SELECT * FROM users WHERE age > $1 LIMIT $2", [18, 10])

# Single row
user = db.query_one("SELECT * FROM users WHERE id = $1", [42])

# Execute (INSERT/UPDATE/DELETE)
db.execute("INSERT INTO users (name, email) VALUES ($1, $2)", ["Alice", "a@b.com"])
```

## With TurboAPI (zero-Python DB routes)

```python
from turboapi import TurboAPI

app = TurboAPI()
app.configure_db("postgres://...", pool_size=16)

@app.db_get("/users/{user_id}", table="users", pk="id")
def get_user(): pass
```

HTTP in, JSON out. Python never touches the data. 128k req/s on DB routes.

## License

MIT
