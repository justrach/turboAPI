#!/usr/bin/env python3
"""Simple test to debug POST body parsing"""

from turboapi import TurboAPI
import time
import threading
import requests

app = TurboAPI(title="Simple Test")

@app.post("/test")
def handler(request_data: dict):
    print(f"Handler called with: {request_data}")
    return {"received": request_data}

# Start server
def start_server():
    app.run(host="127.0.0.1", port=9000)

server_thread = threading.Thread(target=start_server, daemon=True)
server_thread.start()
time.sleep(3)

# Test
print("Sending request...")
response = requests.post("http://127.0.0.1:9000/test", json={"key": "value"})
print(f"Status: {response.status_code}")
print(f"Response: {response.text}")
