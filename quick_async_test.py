from turboapi import TurboAPI
import asyncio

app = TurboAPI()

@app.get('/sync')
def sync_test():
    return {'type': 'sync', 'works': True}

@app.get('/async')
async def async_test():
    await asyncio.sleep(0.001)
    return {'type': 'async', 'works': True}

print("Routes registered:")
for route in app.registry.get_routes():
    print(f"  {route.method} {route.path} -> {route.handler.__name__}")

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8888)
