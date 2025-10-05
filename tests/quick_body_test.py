"""Quick test for body parsing"""
from satya import Model, Field
from turboapi import TurboAPI

app = TurboAPI(title="Body Test", version="1.0.0")

# Test 1: Simple body parsing
@app.post("/simple")
def simple_handler(name: str, age: int = 25):
    return {"name": name, "age": age}

# Test 2: Satya model
class User(Model):
    name: str = Field(min_length=1)
    email: str

@app.post("/model")
def model_handler(user: User):
    return {"user": user.model_dump()}, 201

@app.get("/")
def root():
    return {"status": "ok"}

if __name__ == "__main__":
    print("Starting test server on http://127.0.0.1:8888")
    print("Test with:")
    print('  curl -X POST http://127.0.0.1:8888/simple -H "Content-Type: application/json" -d \'{"name": "Alice", "age": 30}\'')
    print('  curl -X POST http://127.0.0.1:8888/model -H "Content-Type: application/json" -d \'{"name": "Bob", "email": "bob@example.com"}\'')
    
    app.configure_rate_limiting(enabled=False)
    app.run(host="127.0.0.1", port=8888)
