
import asyncio
from turboapi import TurboAPI

app = TurboAPI(title="TurboAPI Benchmark", version="1.0.0")

@app.get("/sync")
def sync_endpoint():
    """Sync endpoint - minimal processing"""
    return {"framework": "TurboAPI", "type": "sync", "status": "ok"}

@app.get("/async")
async def async_endpoint():
    """Async endpoint - with async sleep"""
    await asyncio.sleep(0.001)  # 1ms async delay
    return {"framework": "TurboAPI", "type": "async", "status": "ok"}

@app.get("/health")
def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    print("🚀 Starting TurboAPI server on http://127.0.0.1:8000")
    app.run(host="127.0.0.1", port=8000)
