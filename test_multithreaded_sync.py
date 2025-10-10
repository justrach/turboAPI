"""
Test multi-threaded sync handler performance
"""
from turboapi import TurboAPI
import time

app = TurboAPI()

# Counter to track concurrent execution
execution_times = []

@app.get("/sync")
def sync_handler():
    """Sync handler that should execute in parallel threads."""
    start = time.time()
    # Simulate some CPU work
    result = sum(i * i for i in range(1000))
    duration = time.time() - start
    execution_times.append(duration)
    return {"result": result, "duration_ms": duration * 1000}

@app.get("/")
def root():
    return {"message": "Multi-threaded sync test", "handlers": len(execution_times)}

if __name__ == "__main__":
    print("🚀 Starting TurboAPI v0.5.0 - Multi-threaded Sync Handler Test")
    print("=" * 70)
    app.run(host="127.0.0.1", port=8080)
