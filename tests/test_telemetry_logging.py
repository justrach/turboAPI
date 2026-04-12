"""Tests for structured logging + telemetry system (Phase 1).

Verifies: Zig logger output, level filtering, JSON format, Python logger,
telemetry init from env vars, end-to-end integration.
"""

import json
import os
import subprocess
import sys


def _run_script(script, env_extra=None):
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    return result.stdout, result.stderr


def _run_server_subprocess(env_extra=None):
    server_script = """
from turboapi import TurboAPI
app = TurboAPI()

@app.get("/hello")
def hello():
    return {"msg": "hi"}

app.run()
"""
    env = os.environ.copy()
    env["TURBO_LOG_LEVEL"] = "debug"
    if env_extra:
        env.update(env_extra)
    try:
        result = subprocess.run(
            [sys.executable, "-c", server_script],
            capture_output=True,
            text=True,
            timeout=3,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        stderr = e.stderr or b""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return stderr
    return result.stderr


# ── Zig logger: text format ────────────────────────────────────────────────


class TestZigLoggerText:
    def test_startup_messages_appear(self):
        out = _run_server_subprocess()
        assert "TurboNet-Zig server listening on" in out
        assert "Zig HTTP core active" in out

    def test_no_emoji_prefix(self):
        out = _run_server_subprocess()
        assert "🚀" not in out
        assert "🎯" not in out

    def test_cache_enable_logged(self):
        out = _run_server_subprocess()
        assert "Response caching enabled" in out


# ── Zig logger: JSON format ────────────────────────────────────────────────


class TestZigLoggerJSON:
    def test_json_lines_output(self):
        out = _run_server_subprocess(env_extra={"TURBO_LOG_FORMAT": "json"})
        json_lines = [ln for ln in out.strip().split("\n") if ln.startswith("{")]
        assert len(json_lines) >= 2, f"Expected >= 2 JSON lines, got {len(json_lines)}: {out!r}"

    def test_json_has_required_fields(self):
        out = _run_server_subprocess(env_extra={"TURBO_LOG_FORMAT": "json"})
        json_lines = [ln for ln in out.strip().split("\n") if ln.startswith("{")]
        for line in json_lines[:3]:
            obj = json.loads(line)
            assert "ts" in obj, f"Missing 'ts' in {obj}"
            assert "level" in obj, f"Missing 'level' in {obj}"
            assert "msg" in obj, f"Missing 'msg' in {obj}"

    def test_json_levels_are_lowercase(self):
        out = _run_server_subprocess(env_extra={"TURBO_LOG_FORMAT": "json"})
        json_lines = [ln for ln in out.strip().split("\n") if ln.startswith("{")]
        for line in json_lines[:3]:
            obj = json.loads(line)
            assert obj["level"] in ("debug", "info", "warn", "error"), f"Bad level: {obj['level']}"

    def test_json_timestamps_are_numeric(self):
        out = _run_server_subprocess(env_extra={"TURBO_LOG_FORMAT": "json"})
        json_lines = [ln for ln in out.strip().split("\n") if ln.startswith("{")]
        for line in json_lines[:3]:
            obj = json.loads(line)
            assert isinstance(obj["ts"], (int, float)), f"ts not numeric: {obj['ts']!r}"


# ── Zig logger: level filtering ─────────────────────────────────────────────


class TestZigLevelFilter:
    def test_warn_suppresses_info(self):
        out = _run_server_subprocess(env_extra={"TURBO_LOG_LEVEL": "warn"})
        assert "TurboNet-Zig server listening" not in out
        assert "Response caching enabled" not in out

    def test_error_suppresses_everything(self):
        out = _run_server_subprocess(env_extra={"TURBO_LOG_LEVEL": "error"})
        assert "TurboNet-Zig server listening" not in out
        assert "Response caching enabled" not in out

    def test_debug_shows_info_messages(self):
        out = _run_server_subprocess(env_extra={"TURBO_LOG_LEVEL": "debug"})
        assert "TurboNet-Zig server listening" in out
        assert "Response caching enabled" in out


# ── Zig logger: JSON format + level filtering combined ──────────────────────


class TestZigJSONLevelFilter:
    def test_warn_level_json_format_only_warn_error(self):
        out = _run_server_subprocess(
            env_extra={
                "TURBO_LOG_LEVEL": "warn",
                "TURBO_LOG_FORMAT": "json",
            }
        )
        json_lines = [ln for ln in out.strip().split("\n") if ln.startswith("{")]
        for line in json_lines:
            obj = json.loads(line)
            assert obj["level"] in ("warn", "error"), f"Got {obj['level']} when level=warn: {obj}"


# ── Python logger ───────────────────────────────────────────────────────────


class TestPythonLogger:
    def test_get_logger_returns_logger(self):
        import logging

        from turboapi.logger import get_logger

        log = get_logger("test_turboapi_unique_1")
        assert isinstance(log, logging.Logger)

    def test_python_logger_text_format(self):
        _, stderr = _run_script(
            'from turboapi.logger import get_logger; log = get_logger("test_text_unique"); log.info("hello world")',
            env_extra={"TURBO_LOG_LEVEL": "DEBUG", "TURBO_LOG_FORMAT": "text"},
        )
        assert "hello world" in stderr

    def test_python_logger_json_format(self):
        _, stderr = _run_script(
            'from turboapi.logger import get_logger; log = get_logger("test_json_unique"); log.info("hello world")',
            env_extra={"TURBO_LOG_LEVEL": "DEBUG", "TURBO_LOG_FORMAT": "json"},
        )
        json_lines = [ln for ln in stderr.strip().split("\n") if ln.startswith("{")]
        assert len(json_lines) >= 1
        obj = json.loads(json_lines[0])
        assert obj["msg"] == "hello world"
        assert obj["level"] == "info"
        assert "ts" in obj

    def test_python_logger_level_filter(self):
        _, stderr = _run_script(
            'from turboapi.logger import get_logger; log = get_logger("test_filter_unique"); '
            'log.debug("nope"); log.warning("yes")',
            env_extra={"TURBO_LOG_LEVEL": "WARNING", "TURBO_LOG_FORMAT": "text"},
        )
        assert "nope" not in stderr
        assert "yes" in stderr

    def test_python_logger_json_trace_id(self):
        _, stderr = _run_script(
            'from turboapi.logger import get_logger; log = get_logger("test_trace_unique"); '
            'log.info("with trace", extra={"trace_id": "abc123"})',
            env_extra={"TURBO_LOG_LEVEL": "DEBUG", "TURBO_LOG_FORMAT": "json"},
        )
        json_lines = [ln for ln in stderr.strip().split("\n") if ln.startswith("{")]
        obj = json.loads(json_lines[0])
        assert obj["trace_id"] == "abc123"

    def test_python_logger_no_handler_duplicate(self):
        _, stderr = _run_script(
            "from turboapi.logger import get_logger; "
            'log = get_logger("test_dedup_unique"); '
            'log = get_logger("test_dedup_unique"); '
            'log.info("once")',
            env_extra={"TURBO_LOG_LEVEL": "DEBUG", "TURBO_LOG_FORMAT": "json"},
        )
        json_lines = [ln for ln in stderr.strip().split("\n") if ln.startswith("{")]
        assert len(json_lines) == 1, f"Duplicate handlers? Got {len(json_lines)} lines"


# ── Defaults: no env vars ───────────────────────────────────────────────────


class TestDefaults:
    def test_default_shows_info_not_debug(self):
        out = _run_server_subprocess(
            env_extra={
                "TURBO_LOG_LEVEL": "",  # unset → default info
            }
        )
        assert "TurboNet-Zig server listening" in out


# ── TestClient integration: logger works in-process ─────────────────────────


class TestInProcess:
    def test_testclient_with_logger(self):
        from turboapi import TurboAPI
        from turboapi.testclient import TestClient

        app = TurboAPI()

        @app.get("/ping")
        def ping():
            return {"pong": True}

        client = TestClient(app)
        r = client.get("/ping")
        assert r.status_code == 200
        assert r.json() == {"pong": True}

    def test_python_logger_in_process(self):
        import io
        import logging

        from turboapi.logger import get_logger

        log = get_logger("test_in_proc_unique")
        captured = io.StringIO()
        handler = logging.StreamHandler(captured)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        log.addHandler(handler)
        log.info("test message in process")
        output = captured.getvalue()
        assert "test message in process" in output
