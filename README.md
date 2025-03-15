# Tatsat

A high-performance web framework with elegant syntax and powerful validation, built on Starlette and using satya for data validation.

## Features

- **Modern**: Built on top of Starlette, a lightweight ASGI framework
- **Fast**: Utilizes satya's high-performance validation engine
- **Developer-friendly**: Intuitive, FastAPI-like syntax for rapid development
- **Type-safe**: Leverages Python type hints with satya models
- **Automatic API documentation**: Swagger UI and ReDoc integration

## Installation

```bash
# First install the framework
pip install -e .

# Make sure you have satya installed (or in your project directory)
# pip install satya
```

## Quick Start

Here's a minimal example to get you started:

```python
from tatsat import Tatsat
from src.satya import Model, Field
from typing import List, Optional

app = Tatsat(title="Tatsat Demo")

# Define your data models with satya
class Item(Model):
    name: str = Field()
    description: Optional[str] = Field(required=False)
    price: float = Field(gt=0)
    tax: Optional[float] = Field(required=False)
    tags: List[str] = Field(default=[])

# Create API endpoints with typed parameters
@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/items/{item_id}")
def read_item(item_id: int, q: Optional[str] = None):
    return {"item_id": item_id, "q": q}

@app.post("/items/", response_model=Item)
def create_item(item: Item):
    return item

# Run the application with Uvicorn
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

## API Documentation

Tatsat automatically generates interactive API documentation using Swagger UI and ReDoc. Access them at `/docs` and `/redoc` respectively after starting your application.

## Dependencies

Tatsat depends on the following packages:

- starlette
- uvicorn
- satya (for data validation)

## License

MIT License
