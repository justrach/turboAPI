"""Test app from issue #46 — verifies TurboAPI works end-to-end."""
from dhi import BaseModel
from turboapi import TurboAPI

app = TurboAPI()


class Item(BaseModel):
    name: str
    price: float
    quantity: int = 1


@app.get("/")
def hello():
    return {"message": "Hello World"}


@app.get("/items/{item_id}")
def get_item(item_id: int):
    return {"item_id": item_id, "name": "Widget"}


@app.post("/items")
def create_item(item: Item):
    return {"item": item.model_dump(), "created": True}


if __name__ == "__main__":
    app.run(host="0.0.0.0")
