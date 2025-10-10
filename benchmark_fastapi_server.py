
import asyncio
import uvicorn
from fastapi import FastAPI

app = FastAPI(title="FastAPI Benchmark", version="1.0.0")

@app.get("/sync")
def sync_endpoint():
    """Sync endpoint - minimal processing"""
    return {"framework": "FastAPI", "type": "sync", "status": "ok"}

@app.get("/async")
async def async_endpoint():
    """Async endpoint - with async sleep"""
    await asyncio.sleep(0.001)  # 1ms async delay
    return {"framework": "FastAPI", "type": "async", "status": "ok"}

@app.get("/health")
def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    print("🚀 Starting FastAPI server on http://127.0.0.1:8001")
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="error")
