"""Direct ASGI fallback parity tests for FastAPI-style surfaces."""

import asyncio
import json
from pathlib import Path
from typing import Annotated

from dhi import BaseModel
from turboapi import Cookie, Depends, File, Form, Header, Query, TurboAPI, UploadFile
from turboapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from turboapi.staticfiles import StaticFiles


def call_asgi(app, method="GET", path="/", *, query_string=b"", body=b"", headers=None):
    sent = []
    received = False

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query_string,
        "headers": headers or [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    bodies = [m.get("body", b"") for m in sent if m["type"] == "http.response.body"]
    return {
        "status": start["status"],
        "headers": start.get("headers", []),
        "body": b"".join(bodies),
        "messages": sent,
    }


def header(resp, name: bytes):
    for key, value in resp["headers"]:
        if key.lower() == name.lower():
            return value
    return None


def as_json(resp):
    return json.loads(resp["body"])


def test_asgi_response_objects_preserve_status_headers_and_body():
    app = TurboAPI()

    @app.get("/created")
    def created():
        return JSONResponse({"ok": True}, status_code=201, headers={"x-test": "yes"})

    @app.get("/html")
    def html():
        return HTMLResponse("<h1>hello</h1>")

    @app.get("/plain")
    def plain():
        return PlainTextResponse("hello")

    created_resp = call_asgi(app, path="/created")
    assert created_resp["status"] == 201
    assert as_json(created_resp) == {"ok": True}
    assert header(created_resp, b"x-test") == b"yes"

    html_resp = call_asgi(app, path="/html")
    assert html_resp["status"] == 200
    assert html_resp["body"] == b"<h1>hello</h1>"
    assert header(html_resp, b"content-type") == b"text/html"

    plain_resp = call_asgi(app, path="/plain")
    assert plain_resp["body"] == b"hello"
    assert header(plain_resp, b"content-type") == b"text/plain"


def test_asgi_streaming_response_sends_chunks():
    app = TurboAPI()

    @app.get("/stream")
    def stream():
        def gen():
            yield b"one\n"
            yield b"two\n"

        return StreamingResponse(gen(), media_type="text/plain")

    resp = call_asgi(app, path="/stream")
    assert resp["status"] == 200
    assert resp["body"] == b"one\ntwo\n"
    body_messages = [m for m in resp["messages"] if m["type"] == "http.response.body"]
    assert body_messages[0]["more_body"] is True
    assert body_messages[-1].get("more_body") is False


def test_asgi_depends_json_model_query_header_cookie_and_form():
    class ItemIn(BaseModel):
        name: str
        price: float

    class ItemOut(BaseModel):
        name: str
        price: float
        taxed: float

    def get_session():
        return {"session": True}

    SessionDep = Annotated[dict, Depends(get_session)]
    app = TurboAPI()

    @app.get("/items/{item_id}")
    def read_item(item_id: int, limit: int = Query(default=10, alias="l")):
        return {"item_id": item_id, "limit": limit, "limit_type": type(limit).__name__}

    @app.post("/items")
    def create_item(session: SessionDep, item: ItemIn):
        assert session == {"session": True}
        return ItemOut(name=item.name, price=item.price, taxed=round(item.price * 1.2, 2))

    @app.post("/login")
    def login(username: str = Form(), password: str = Form()):
        return {"username": username, "password_len": len(password)}

    @app.get("/headers")
    def headers(x_token: str = Header(alias="X-Token"), session_id: str = Cookie(default="none")):
        return {"x_token": x_token, "session_id": session_id}

    query_resp = call_asgi(app, path="/items/42", query_string=b"l=5")
    assert as_json(query_resp) == {"item_id": 42, "limit": 5, "limit_type": "int"}

    body = json.dumps({"name": "book", "price": 10.0}).encode()
    model_resp = call_asgi(
        app,
        method="POST",
        path="/items",
        body=body,
        headers=[[b"content-type", b"application/json"]],
    )
    assert model_resp["status"] == 200
    assert as_json(model_resp)["taxed"] == 12.0

    form_resp = call_asgi(
        app,
        method="POST",
        path="/login",
        body=b"username=rach&password=secret",
        headers=[[b"content-type", b"application/x-www-form-urlencoded"]],
    )
    assert as_json(form_resp) == {"username": "rach", "password_len": 6}

    header_resp = call_asgi(
        app,
        path="/headers",
        headers=[[b"x-token", b"tok"], [b"cookie", b"session_id=s123"]],
    )
    assert as_json(header_resp) == {"x_token": "tok", "session_id": "s123"}


def test_asgi_file_upload_openapi_docs_redoc_and_static(tmp_path: Path):
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "hello.txt").write_text("static-ok")

    app = TurboAPI(title="ASGI Smoke")
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.post("/upload")
    def upload(file: UploadFile = File()):
        return {"filename": file.filename, "content_type": file.content_type}

    boundary = "----testboundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="x.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        "hello\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    upload_resp = call_asgi(
        app,
        method="POST",
        path="/upload",
        body=body,
        headers=[[b"content-type", f"multipart/form-data; boundary={boundary}".encode()]],
    )
    assert as_json(upload_resp) == {"filename": "x.txt", "content_type": "text/plain"}

    openapi_resp = call_asgi(app, path="/openapi.json")
    assert openapi_resp["status"] == 200
    assert as_json(openapi_resp)["info"]["title"] == "ASGI Smoke"

    docs_resp = call_asgi(app, path="/docs")
    assert docs_resp["status"] == 200
    assert b"swagger-ui" in docs_resp["body"]

    redoc_resp = call_asgi(app, path="/redoc")
    assert redoc_resp["status"] == 200
    assert b"redoc" in redoc_resp["body"].lower()

    static_resp = call_asgi(app, path="/static/hello.txt")
    assert static_resp["status"] == 200
    assert static_resp["body"] == b"static-ok"
