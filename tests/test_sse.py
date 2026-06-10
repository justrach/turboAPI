"""Tests for SSE (Server-Sent Events) wire format and EventSourceResponse.

Covers `python/turboapi/sse.py`:
* `ServerSentEvent` dataclass + `.encode()`
* `format_sse_event` wire format
* `EventSourceResponse` headers / media type / iterator wrapping

Note: end-to-end streaming over the Zig HTTP server is NOT exercised here —
the current Zig dispatch path sends `Response.body` directly and does not
yet iterate `StreamingResponse.body_iterator()`. Tracking that gap in a
follow-up issue. These tests lock in the parts that are functional today
(everything below the transport layer).
"""

from __future__ import annotations

import asyncio
import json

import pytest
from turboapi.sse import EventSourceResponse, ServerSentEvent, format_sse_event

# ---------------------------------------------------------------------------
# format_sse_event / ServerSentEvent.encode wire format
# ---------------------------------------------------------------------------


def test_format_data_only_string():
    out = format_sse_event(ServerSentEvent(data="hello"))
    assert out == "data: hello\n\n"


def test_format_data_only_dict_serializes_json():
    out = format_sse_event(ServerSentEvent(data={"a": 1, "b": "two"}))
    # Single-line JSON → single `data:` line
    assert out.startswith("data: ")
    assert out.endswith("\n\n")
    payload = out.removeprefix("data: ").removesuffix("\n\n")
    assert json.loads(payload) == {"a": 1, "b": "two"}


def test_format_data_multiline_string_emits_one_data_per_line():
    out = format_sse_event(ServerSentEvent(data="line1\nline2\nline3"))
    # Each newline-separated chunk becomes its own `data:` line
    assert "data: line1" in out
    assert "data: line2" in out
    assert "data: line3" in out
    assert out.endswith("\n\n")


def test_format_event_name():
    out = format_sse_event(ServerSentEvent(data="hi", event="update"))
    assert "event: update\n" in out
    assert "data: hi\n" in out


def test_format_id_field():
    out = format_sse_event(ServerSentEvent(data="hi", id="42"))
    assert "id: 42\n" in out


def test_format_id_can_be_int():
    out = format_sse_event(ServerSentEvent(data="hi", id=99))
    assert "id: 99\n" in out


def test_format_retry_field():
    out = format_sse_event(ServerSentEvent(data="hi", retry=3000))
    assert "retry: 3000\n" in out


def test_format_comment_only():
    out = format_sse_event(ServerSentEvent(comment="ping"))
    # Comments are `:` prefixed per the SSE spec.
    assert out.startswith(": ping")
    assert out.endswith("\n\n")


def test_format_multiline_comment():
    out = format_sse_event(ServerSentEvent(comment="line1\nline2"))
    assert ": line1" in out
    assert ": line2" in out


def test_format_combined_fields_in_canonical_order():
    out = format_sse_event(
        ServerSentEvent(
            data="payload",
            event="msg",
            id=7,
            retry=1500,
            comment="diagnostic",
        )
    )
    # Field order per the sse.py implementation: comment → event → id → retry → data.
    # Locking that order in so reorder regressions are visible.
    lines = out.splitlines()
    nonempty = [ln for ln in lines if ln]
    assert nonempty[0].startswith(": ")
    assert nonempty[1].startswith("event: ")
    assert nonempty[2].startswith("id: ")
    assert nonempty[3].startswith("retry: ")
    assert nonempty[4].startswith("data: ")


def test_encode_method_matches_format_function():
    evt = ServerSentEvent(data={"x": 1}, event="e", id="1")
    assert evt.encode() == format_sse_event(evt)


def test_format_terminates_with_double_newline():
    # SSE protocol requires \n\n to delimit events.
    out = format_sse_event(ServerSentEvent(data="x"))
    assert out.endswith("\n\n")


# ---------------------------------------------------------------------------
# EventSourceResponse construction
# ---------------------------------------------------------------------------


async def _gen_three():
    yield ServerSentEvent(data="a")
    yield ServerSentEvent(data="b")
    yield ServerSentEvent(data="c")


def test_event_source_response_sets_sse_headers():
    resp = EventSourceResponse(_gen_three())
    assert resp.media_type == "text/event-stream"
    # SSE-required headers should be present:
    assert resp.headers["content-type"] == "text/event-stream"
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["connection"] == "keep-alive"
    # Disable nginx/proxy buffering so events flush immediately:
    assert resp.headers["x-accel-buffering"] == "no"


def test_event_source_response_status_code_default_200():
    resp = EventSourceResponse(_gen_three())
    assert resp.status_code == 200


def test_event_source_response_custom_headers_merge():
    resp = EventSourceResponse(_gen_three(), headers={"x-custom": "yes"})
    assert resp.headers["x-custom"] == "yes"
    # SSE defaults must not be overridden by partial header dict:
    assert resp.headers["content-type"] == "text/event-stream"


def test_event_source_response_iterates_events_and_encodes_each():
    """Drain the wrapped iterator and confirm each yield is SSE-encoded."""
    resp = EventSourceResponse(_gen_three(), ping_interval=999)

    async def drain():
        out = []
        async for chunk in resp._wrap_with_ping(_gen_three()):
            out.append(chunk)
            if len(out) >= 3:
                break
        return out

    chunks = asyncio.run(drain())
    assert len(chunks) == 3
    assert chunks[0] == "data: a\n\n"
    assert chunks[1] == "data: b\n\n"
    assert chunks[2] == "data: c\n\n"


def test_event_source_response_auto_wraps_dict_as_data():
    async def gen():
        yield {"key": "val"}

    resp = EventSourceResponse(gen(), ping_interval=999)

    async def drain():
        async for chunk in resp._wrap_with_ping(gen()):
            return chunk

    chunk = asyncio.run(drain())
    assert chunk.startswith("data: ")
    assert json.loads(chunk.removeprefix("data: ").removesuffix("\n\n")) == {"key": "val"}


def test_event_source_response_auto_wraps_string_as_data():
    async def gen():
        yield "plain"

    resp = EventSourceResponse(gen(), ping_interval=999)

    async def drain():
        async for chunk in resp._wrap_with_ping(gen()):
            return chunk

    chunk = asyncio.run(drain())
    assert chunk == "data: plain\n\n"


# ---------------------------------------------------------------------------
# Streaming-over-Zig integration gap (acknowledged, not executed)
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "End-to-end SSE streaming over the Zig HTTP server is not yet wired up: "
        "request_handler dispatches `Response.body` directly and does not iterate "
        "StreamingResponse.body_iterator(). Tracked in follow-up issue."
    )
)
def test_event_source_response_end_to_end_over_zig_server():
    """Reserved placeholder — un-skip when the Zig dispatch path streams chunks."""
    raise NotImplementedError
