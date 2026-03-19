"""
TechEmpower Framework Benchmark — TurboAPI (Zig HTTP core)

Implements:
  /json       — {"message": "Hello, World!"}
  /plaintext  — Hello, World!
"""
import os

from turboapi import TurboAPI
from turboapi.responses import PlainTextResponse

app = TurboAPI()

# Disable rate limiting for benchmarks
os.environ["TURBO_DISABLE_RATE_LIMITING"] = "1"


@app.get("/json")
def json_test():
    return {"message": "Hello, World!"}


@app.get("/plaintext")
def plaintext_test():
    return PlainTextResponse(content="Hello, World!")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
