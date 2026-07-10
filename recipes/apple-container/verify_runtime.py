#!/usr/bin/env python3
"""Fail unless this image is using TurboAPI's native arm64 Zig backend."""

import importlib.machinery
import importlib.util
import pathlib
import platform
import sys
import sysconfig

assert platform.system() == "Linux", platform.system()
assert platform.machine() == "aarch64", platform.machine()
assert sys.version_info[:2] == (3, 14), sys.version
assert sysconfig.get_config_var("Py_GIL_DISABLED") == 1
assert hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled()
assert "314t" in (sysconfig.get_config_var("SOABI") or "")

spec = importlib.util.find_spec("turboapi.turbonet")
assert spec is not None, "turbonet extension is absent"
assert isinstance(spec.loader, importlib.machinery.ExtensionFileLoader), spec.loader
assert spec.origin, "turbonet extension has no origin"
extension = pathlib.Path(spec.origin).resolve()
assert extension.is_file(), extension
assert "site-packages" in extension.parts, extension

import turboapi.native_integration as native  # noqa: E402
import turboapi.turbonet as turbonet  # noqa: E402

assert hasattr(turbonet, "TurboServer")
assert hasattr(turbonet, "ResponseView")
assert native.NATIVE_CORE_AVAILABLE is True
assert native._BACKEND == "zig"
assert native.turbonet is turbonet

print(
    {
        "machine": platform.machine(),
        "python": platform.python_version(),
        "soabi": sysconfig.get_config_var("SOABI"),
        "extension": str(extension),
        "backend": native._BACKEND,
    }
)
