import asyncio
import json

from turboapi import HTTPException, TurboAPI
from turboapi.request_handler import (
    create_fast_handler,
    create_pos_handler,
)
from turboapi.routing import HTTPMethod
from turboapi.testclient import TestClient


class _Route:
    method = HTTPMethod.GET
    path = "/boom"


def test_testclient_redacts_unexpected_errors_by_default():
    app = TurboAPI()

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret-token")

    response = TestClient(app).get("/boom")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    assert "secret-token" not in response.text


def test_testclient_debug_includes_unexpected_error_detail():
    app = TurboAPI(debug=True)

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret-token")

    response = TestClient(app).get("/boom")

    assert response.status_code == 500
    assert response.json() == {"detail": "secret-token"}


def test_http_exception_detail_is_preserved():
    app = TurboAPI()

    @app.get("/nope")
    def nope():
        raise HTTPException(status_code=418, detail="teapot")

    response = TestClient(app).get("/nope")

    assert response.status_code == 418
    assert response.json() == {"detail": "teapot"}


def test_fast_handler_redacts_unexpected_errors_by_default():
    def boom():
        raise RuntimeError("secret-token")

    handler = create_fast_handler(boom, _Route())
    status, content_type, body = handler()

    assert status == 500
    assert content_type == "application/json"
    assert json.loads(body) == {"error": "Internal Server Error"}
    assert "secret-token" not in body


def test_fast_handler_debug_includes_unexpected_error_detail():
    def boom():
        raise RuntimeError("secret-token")

    handler = create_fast_handler(boom, _Route(), debug=True)
    status, _, body = handler()

    assert status == 500
    assert json.loads(body) == {"error": "Internal Server Error", "detail": "secret-token"}


def test_pos_handler_redacts_unexpected_errors_by_default():
    def boom():
        raise RuntimeError("secret-token")

    handler = create_pos_handler(boom)
    status, _, body = handler()

    assert status == 500
    assert json.loads(body) == {"error": "Internal Server Error"}


def test_handle_request_redacts_unexpected_errors_by_default():
    app = TurboAPI()

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret-token")

    result = asyncio.run(app.handle_request("GET", "/boom"))

    assert result == {"error": "Internal Server Error", "status_code": 500}


def test_handle_request_debug_includes_unexpected_error_detail():
    app = TurboAPI(debug=True)

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret-token")

    result = asyncio.run(app.handle_request("GET", "/boom"))

    assert result == {
        "error": "Internal Server Error",
        "status_code": 500,
        "detail": "secret-token",
    }
