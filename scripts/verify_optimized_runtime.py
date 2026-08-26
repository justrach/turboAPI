#!/usr/bin/env python3
"""Fail closed unless the active CPython is an optimized free-threaded build."""

from __future__ import annotations

import argparse
import importlib
import json
import platform
import shlex
import sys
import sysconfig
from typing import Any


def _has_config_option(tokens: list[str], option: str) -> bool:
    return any(token == option or token.startswith(f"{option}=") for token in tokens)


def runtime_report(*, inspect_native: bool = False) -> dict[str, Any]:
    """Collect build facts without deciding which guarantees are required."""
    config_args = str(sysconfig.get_config_var("CONFIG_ARGS") or "")
    report: dict[str, Any] = {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "gil_enabled": bool(sys._is_gil_enabled()),
        "py_gil_disabled": sysconfig.get_config_var("Py_GIL_DISABLED"),
        "config_args": config_args,
        "machine": platform.machine(),
        "soabi": sysconfig.get_config_var("SOABI"),
    }
    if inspect_native:
        package = importlib.import_module("turboapi")
        native = importlib.import_module("turboapi.turbonet")
        report["turboapi_version"] = getattr(package, "__version__", None)
        report["native_module"] = native.__file__
    return report


def validation_errors(
    report: dict[str, Any],
    *,
    expected_version: str,
    require_bolt: bool = False,
    require_native: bool = False,
) -> list[str]:
    """Return every violated runtime contract."""
    errors: list[str] = []
    tokens = shlex.split(str(report.get("config_args") or ""))

    if report.get("implementation") != "CPython":
        errors.append(f"expected CPython, found {report.get('implementation')!r}")
    if report.get("version") != expected_version:
        errors.append(f"expected Python {expected_version}, found {report.get('version')!r}")
    if report.get("gil_enabled") is not False or report.get("py_gil_disabled") != 1:
        errors.append("CPython must be built free-threaded with the GIL disabled")

    required = ["--disable-gil", "--enable-optimizations", "--with-lto", "--with-mimalloc"]
    if require_bolt:
        required.append("--enable-bolt")
    for option in required:
        if not _has_config_option(tokens, option):
            errors.append(f"CPython CONFIG_ARGS is missing {option}")

    if any(token in {"--with-lto=no", "--with-mimalloc=no"} for token in tokens):
        errors.append("CPython CONFIG_ARGS explicitly disables LTO or mimalloc")
    if require_native and not report.get("native_module"):
        errors.append("turboapi.turbonet did not resolve to a native module")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-version", required=True)
    parser.add_argument("--require-bolt", action="store_true")
    parser.add_argument("--require-native", action="store_true")
    args = parser.parse_args()

    try:
        report = runtime_report(inspect_native=args.require_native)
    except Exception as exc:
        raise SystemExit(f"runtime inspection failed: {exc}") from exc

    errors = validation_errors(
        report,
        expected_version=args.expect_version,
        require_bolt=args.require_bolt,
        require_native=args.require_native,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if errors:
        raise SystemExit("runtime contract failed:\n- " + "\n- ".join(errors))
    print("optimized free-threaded runtime contract: PASS")


if __name__ == "__main__":
    main()
