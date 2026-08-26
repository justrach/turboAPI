#!/usr/bin/env python3
"""Deterministic short-response fixture for benchmark_http_c288.py."""

from turboapi import TurboAPI

app = TurboAPI()
response = {"data": [{"embedding": [0.0] * 512}]}


@app.post("/v1/embeddings")
def embeddings():
    return response


@app.post("/v1/codedb/embeddings")
def codedb_embeddings():
    return response


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
