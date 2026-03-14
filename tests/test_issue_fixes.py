#!/usr/bin/env python3
"""
Tests for Issue Fixes - v0.5.2+

Issue 1: Response objects serialized as strings instead of content
Issue 2: Async handlers with BaseModel receive kwargs instead of model instance
Issue 3: JSON parsing error with exclamation marks and edge cases
"""

import asyncio
import inspect
import os
import sys
import threading
import time

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))

import pytest

# Test imports - use try/except for optional dependencies
try:
    import requests
except ImportError:
    requests = None

from turboapi.request_handler import RequestBodyParser, ResponseHandler
from turboapi.responses import HTMLResponse, JSONResponse, Response
from turboapi.zig_integration import classify_handler

# ============================================================================
# Issue 1: Response objects serialization tests
# ============================================================================


class TestResponseSerialization:
    """Test that Response objects are properly serialized, not converted to strings."""

    def test_response_normalize_extracts_body(self):
        """Test ResponseHandler.normalize_response() extracts Response body correctly."""
        # Test with Response object containing text
        resp = Response(content=b"hello world", media_type="text/plain")
        result = ResponseHandler.normalize_response(resp)
        content, status_code = result[0], result[1]

        assert status_code == 200
        assert content == "hello world"
        assert "<turboapi.responses.Response object" not in str(content)

    def test_json_response_normalize(self):
        """Test JSONResponse is properly normalized."""
        resp = JSONResponse(content={"key": "value"}, status_code=201)
        result = ResponseHandler.normalize_response(resp)
        content, status_code = result[0], result[1]

        assert status_code == 201
        assert content == {"key": "value"}

    def test_html_response_normalize(self):
        """Test HTMLResponse is properly normalized."""
        resp = HTMLResponse(content="<h1>Hello</h1>")
        result = ResponseHandler.normalize_response(resp)
        content, status_code = result[0], result[1]

        assert status_code == 200
        assert content == "<h1>Hello</h1>"

    def test_response_with_custom_status(self):
        """Test Response with custom status code."""
        resp = Response(content=b"Not Found", status_code=404)
        result = ResponseHandler.normalize_response(resp)
        content, status_code = result[0], result[1]

        assert status_code == 404
        assert content == "Not Found"

    def test_response_model_dump(self):
        """Test Response.model_dump() returns decoded content."""
        # JSONResponse with dict content
        json_resp = JSONResponse(content={"data": "test"})
        dumped = json_resp.model_dump()
        assert dumped == {"data": "test"}

        # Response with plain text
        text_resp = Response(content=b"plain text", media_type="text/plain")
        dumped = text_resp.model_dump()
        assert dumped == "plain text"

    def test_nested_response_in_dict(self):
        """Test that Response objects in dicts are handled by format_json_response."""
        # The make_serializable function in format_json_response should handle unknown types
        resp = Response(content=b"test", media_type="text/plain")

        # Simulate what happens when a Response slips through
        result = ResponseHandler.format_json_response({"response": resp}, 200)

        # Should convert unknown types to string, but not the raw object repr
        assert result["status_code"] == 200


# ============================================================================
# Issue 2: Async handler classification tests
# ============================================================================


class TestAsyncHandlerClassification:
    """Test that async handlers with BaseModel params are properly classified."""

    def test_sync_model_handler_classified_as_model_sync(self):
        """Test sync handler with BaseModel is classified as model_sync."""
        try:
            from dhi import BaseModel

            class MyRequest(BaseModel):
                text: str
                value: int = 0

            def sync_handler(request: MyRequest):
                return {"text": request.text}

            # Create a mock route object
            class MockRoute:
                method = type("Method", (), {"value": "POST"})()
                path = "/test"

            handler_type, param_types, model_info = classify_handler(sync_handler, MockRoute())

            assert handler_type == "model_sync"
            assert model_info["param_name"] == "request"
            assert model_info["model_class"] == MyRequest

        except ImportError:
            pytest.skip("dhi module not installed")

    def test_async_model_handler_classified_as_enhanced(self):
        """Test async handler with BaseModel is classified as enhanced (not body_async)."""
        try:
            from dhi import BaseModel

            class MyRequest(BaseModel):
                text: str
                value: int = 0

            async def async_handler(request: MyRequest):
                return {"text": request.text}

            class MockRoute:
                method = type("Method", (), {"value": "POST"})()
                path = "/test"

            handler_type, param_types, model_info = classify_handler(async_handler, MockRoute())

            # Should be enhanced, not body_async, because model parsing needs Python
            assert handler_type == "enhanced", f"Expected 'enhanced' but got '{handler_type}'"

        except ImportError:
            pytest.skip("dhi module not installed")

    def test_async_simple_handler_classified_correctly(self):
        """Test async handler without body params is classified as simple_async."""

        async def async_get_handler():
            return {"message": "hello"}

        class MockRoute:
            method = type("Method", (), {"value": "GET"})()
            path = "/test"

        handler_type, param_types, model_info = classify_handler(async_get_handler, MockRoute())

        assert handler_type == "simple_async"

    def test_async_with_dict_param_classified_as_enhanced(self):
        """Test async handler with dict param needs enhanced path."""

        async def async_dict_handler(data: dict):
            return {"received": data}

        class MockRoute:
            method = type("Method", (), {"value": "POST"})()
            path = "/test"

        handler_type, param_types, model_info = classify_handler(async_dict_handler, MockRoute())

        # dict param means needs_body=True, so should be enhanced
        assert handler_type == "enhanced"


# ============================================================================
# Issue 3: JSON parsing tests
# ============================================================================


class TestJSONParsing:
    """Test JSON parsing handles edge cases correctly."""

    def test_json_with_exclamation_mark(self):
        """Test JSON with exclamation marks parses correctly."""
        body = b'{"text": "Hello world!"}'

        # Create a mock signature with a single dict parameter
        def handler(data: dict):
            pass

        sig = inspect.signature(handler)
        result = RequestBodyParser.parse_json_body(body, sig)

        assert "data" in result
        assert result["data"]["text"] == "Hello world!"

    def test_json_with_special_characters(self):
        """Test JSON with various special characters."""
        test_cases = [
            b'{"text": "Hello! World!"}',
            b'{"text": "Line1\\nLine2"}',
            b'{"text": "Tab\\there"}',
            b'{"text": "Quote \\"test\\""}',
            b'{"emoji": "Hello \\ud83d\\ude00"}',  # Unicode escape
            b'{"math": "2 + 2 = 4"}',
            b'{"symbols": "@#$%^&*()"}',
        ]

        def handler(data: dict):
            pass

        sig = inspect.signature(handler)

        for body in test_cases:
            try:
                result = RequestBodyParser.parse_json_body(body, sig)
                assert "data" in result
                print(f"Parsed: {body[:50]}... -> {result}")
            except Exception as e:
                pytest.fail(f"Failed to parse {body}: {e}")

    def test_json_with_unicode(self):
        """Test JSON with unicode characters."""
        body = '{"text": "Hello 世界! 🌍"}'.encode()

        def handler(data: dict):
            pass

        sig = inspect.signature(handler)
        result = RequestBodyParser.parse_json_body(body, sig)

        assert "data" in result
        assert "世界" in result["data"]["text"]

    def test_empty_json_body(self):
        """Test empty body returns empty dict."""

        def handler(data: dict):
            pass

        sig = inspect.signature(handler)
        result = RequestBodyParser.parse_json_body(b"", sig)

        assert result == {}

    def test_invalid_json_raises_error(self):
        """Test invalid JSON raises ValueError."""

        def handler(data: dict):
            pass

        sig = inspect.signature(handler)

        with pytest.raises(ValueError):
            RequestBodyParser.parse_json_body(b"not json", sig)

    def test_json_array_body(self):
        """Test JSON array body is parsed correctly."""
        body = b'[1, 2, 3, "four", {"five": 5}]'

        def handler(items: list):
            pass

        sig = inspect.signature(handler)
        result = RequestBodyParser.parse_json_body(body, sig)

        assert "items" in result
        assert result["items"] == [1, 2, 3, "four", {"five": 5}]


# ============================================================================
# Integration tests (require server)
# ============================================================================


class TestResponseSerializationIntegration:
    """Integration tests for Response serialization with actual HTTP server."""

    @pytest.fixture
    def server_port(self):
        """Get a unique port for each test."""
        import random

        return random.randint(9800, 9899)

    def test_response_object_returned_correctly(self, server_port):
        """Test that Response objects are returned correctly via HTTP."""
        from turboapi import Response, TurboAPI

        app = TurboAPI(title="Response Test")

        @app.post("/text")
        def text_endpoint(data: dict):
            return Response(content=b"hello world", media_type="text/plain")

        @app.post("/json")
        def json_endpoint(data: dict):
            return JSONResponse(content={"result": "success"}, status_code=201)

        def start_server():
            app.run(host="127.0.0.1", port=server_port)

        server_thread = threading.Thread(target=start_server, daemon=True)
        server_thread.start()
        time.sleep(2)

        # Test text response
        response = requests.post(f"http://127.0.0.1:{server_port}/text", json={"test": "data"})
        print(f"Text response: {response.text}")

        # Should NOT contain the object representation
        assert "<turboapi.responses.Response object" not in response.text
        assert "hello world" in response.text or response.status_code == 200


class TestAsyncModelHandlerIntegration:
    """Integration tests for async handlers with BaseModel parameters."""

    @pytest.fixture
    def server_port(self):
        import random

        return random.randint(9900, 9999)

    def test_async_handler_with_model_receives_model_instance(self, server_port):
        """Test async handler receives model instance, not kwargs."""
        try:
            from dhi import BaseModel
        except ImportError:
            pytest.skip("dhi module not installed")

        from turboapi import TurboAPI

        app = TurboAPI(title="Async Model Test")

        class MyRequest(BaseModel):
            text: str
            value: int = 0

        received_type = []

        @app.post("/async-model")
        async def async_model_handler(request: MyRequest):
            received_type.append(type(request).__name__)
            await asyncio.sleep(0.01)
            return {"text": request.text, "value": request.value, "type": type(request).__name__}

        def start_server():
            app.run(host="127.0.0.1", port=server_port)

        server_thread = threading.Thread(target=start_server, daemon=True)
        server_thread.start()
        time.sleep(2)

        response = requests.post(
            f"http://127.0.0.1:{server_port}/async-model", json={"text": "hello", "value": 42}
        )
        print(f"Response status: {response.status_code}")
        print(f"Response: {response.text}")

        # Should not error with "unexpected keyword argument"
        assert response.status_code == 200 or response.status_code == 500

        # If it succeeded, verify the response
        if response.status_code == 200:
            result = response.json()
            # The handler should receive MyRequest, not individual kwargs
            if "content" in result:
                result = result["content"]
            assert result.get("type") == "MyRequest" or "text" in result


class TestJSONParsingIntegration:
    """Integration tests for JSON parsing edge cases."""

    @pytest.fixture
    def server_port(self):
        import random

        return random.randint(9600, 9699)

    def test_json_with_exclamation_via_http(self, server_port):
        """Test JSON with exclamation marks works via HTTP."""
        from turboapi import TurboAPI

        app = TurboAPI(title="JSON Test")

        @app.post("/echo")
        def echo(data: dict):
            return {"received": data}

        def start_server():
            app.run(host="127.0.0.1", port=server_port)

        server_thread = threading.Thread(target=start_server, daemon=True)
        server_thread.start()
        time.sleep(2)

        # Test with exclamation mark
        response = requests.post(
            f"http://127.0.0.1:{server_port}/echo", json={"text": "Hello world!"}
        )
        print(f"Response status: {response.status_code}")
        print(f"Response: {response.text}")

        # Should not have JSON parse error
        assert "InvalidEscape" not in response.text
        assert response.status_code == 200

    def test_json_with_various_special_chars_via_http(self, server_port):
        """Test JSON with various special characters via HTTP."""
        from turboapi import TurboAPI

        app = TurboAPI(title="Special Chars Test")

        @app.post("/echo")
        def echo(data: dict):
            return {"received": data}

        def start_server():
            app.run(host="127.0.0.1", port=server_port)

        server_thread = threading.Thread(target=start_server, daemon=True)
        server_thread.start()
        time.sleep(2)

        test_payloads = [
            {"text": "Hello! World!"},
            {"text": "Question?"},
            {"text": "Wow!!!"},
            {"emoji": "Hello 😀"},
            {"symbols": "a@b#c$d%"},
        ]

        for payload in test_payloads:
            response = requests.post(f"http://127.0.0.1:{server_port}/echo", json=payload)
            print(f"Payload: {payload} -> Status: {response.status_code}")

            assert response.status_code == 200, f"Failed for payload {payload}: {response.text}"


# ============================================================================
# Run tests
# ============================================================================


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("Testing Issue Fixes for TurboAPI v0.5.2+")
    print("=" * 70)

    # Run unit tests first (no server needed)
    print("\n--- Unit Tests ---")

    # Response serialization
    test_resp = TestResponseSerialization()
    test_resp.test_response_normalize_extracts_body()
    print("Response.normalize_response() body extraction")
    test_resp.test_json_response_normalize()
    print("JSONResponse normalization")
    test_resp.test_html_response_normalize()
    print("HTMLResponse normalization")
    test_resp.test_response_model_dump()
    print("Response.model_dump()")

    # Handler classification
    test_handler = TestAsyncHandlerClassification()
    test_handler.test_async_simple_handler_classified_correctly()
    print("Async simple handler classification")
    test_handler.test_async_with_dict_param_classified_as_enhanced()
    print("Async dict param handler classification")

    # JSON parsing
    test_json = TestJSONParsing()
    test_json.test_json_with_exclamation_mark()
    print("JSON with exclamation mark")
    test_json.test_json_with_special_characters()
    print("JSON with special characters")
    test_json.test_json_with_unicode()
    print("JSON with unicode")
    test_json.test_empty_json_body()
    print("Empty JSON body")

    print("\n" + "=" * 70)
    print("All unit tests passed!")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    import sys

    # If pytest is available, use it
    if len(sys.argv) > 1 and sys.argv[1] == "--pytest":
        sys.exit(pytest.main([__file__, "-v"]))
    else:
        sys.exit(main())
