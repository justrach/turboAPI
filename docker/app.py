"""Demo app shipped inside ghcr.io/justrach/turboapi.

Three routes that exercise the framework's hot path:
- GET  /            — zero-arg cached handler (~260k req/s on 4 vCPU)
- GET  /items/{id}  — typed path param (~211k req/s)
- POST /items       — dhi JSON validation (~95k req/s)
"""

import os

from dhi import BaseModel
from turboapi import TurboAPI

app = TurboAPI()


class Item(BaseModel):
    name: str
    price: float
    quantity: int = 1


@app.get("/")
def hello():
    return {"message": "Hello from turboAPI", "ok": True}


@app.get("/items/{item_id}")
def get_item(item_id: int):
    return {"item_id": item_id, "name": "Widget"}


@app.post("/items")
def create_item(item: Item):
    return {"item": item.model_dump(), "created": True}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
