#!/usr/bin/env python3
"""Minimal app used by the Apple container native-runtime smoke test."""

import os

from turboapi import TurboAPI

app = TurboAPI(title="apple-container-smoke")


@app.get("/__turboapi_native_smoke__")
def native_smoke():
    return {
        "ok": True,
        "runtime": "apple-container-linux-arm64-cp314t",
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
