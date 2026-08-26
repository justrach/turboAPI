"""Regression tests for the root Docker image's CPython contract."""

from scripts.verify_optimized_runtime import validation_errors


def _report(config_args: str) -> dict[str, object]:
    return {
        "implementation": "CPython",
        "version": "3.14.7",
        "gil_enabled": False,
        "py_gil_disabled": 1,
        "config_args": config_args,
        "native_module": "/app/python/turboapi/turbonet.so",
    }


def test_optimized_free_threaded_runtime_passes():
    report = _report(
        "--disable-gil --enable-optimizations --with-lto=full --with-mimalloc"
    )
    assert not validation_errors(report, expected_version="3.14.7", require_native=True)


def test_unoptimized_runtime_fails_closed():
    report = _report("--disable-gil --enable-shared --with-mimalloc")
    errors = validation_errors(report, expected_version="3.14.7")
    assert "CPython CONFIG_ARGS is missing --enable-optimizations" in errors
    assert "CPython CONFIG_ARGS is missing --with-lto" in errors


def test_wrong_version_or_enabled_gil_fails_closed():
    report = _report(
        "--disable-gil --enable-optimizations --with-lto=full --with-mimalloc"
    )
    report["version"] = "3.14.8"
    report["gil_enabled"] = True
    errors = validation_errors(report, expected_version="3.14.7")
    assert "expected Python 3.14.7, found '3.14.8'" in errors
    assert "CPython must be built free-threaded with the GIL disabled" in errors


def test_bolt_is_optional_unless_explicitly_required():
    report = _report(
        "--disable-gil --enable-optimizations --with-lto=full --with-mimalloc"
    )
    assert not validation_errors(report, expected_version="3.14.7")
    assert "CPython CONFIG_ARGS is missing --enable-bolt" in validation_errors(
        report, expected_version="3.14.7", require_bolt=True
    )
