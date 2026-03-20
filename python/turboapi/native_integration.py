"""
TurboAPI native backend integration boundary.

This module is the stable Python-facing seam for the native HTTP core.
It loads the Zig turbonet extension and detects free-threading support.
"""

import sys

_BACKEND = None
turbonet = None
NATIVE_CORE_AVAILABLE = False

_FREE_THREADED = hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled()

# ── Load Zig backend ────────────────────────────────────────────────────────
try:
    from turboapi import turbonet as _zig_turbonet

    if hasattr(_zig_turbonet, "TurboServer") and hasattr(_zig_turbonet, "ResponseView"):
        turbonet = _zig_turbonet
        NATIVE_CORE_AVAILABLE = True
        _BACKEND = "zig"
        _ft_tag = " (free-threaded)" if _FREE_THREADED else ""
        print(f"[ZIG] 🚀 Using Zig native backend{_ft_tag}")
    else:
        raise ImportError("Zig turbonet missing required classes")
except ImportError:
    NATIVE_CORE_AVAILABLE = False
    print("[WARN] Native core not available - running in simulation mode")

from .zig_integration import (  # noqa: E402
    ZigIntegratedTurboAPI,
)


class NativeIntegratedTurboAPI(ZigIntegratedTurboAPI):
    """Backend-neutral alias for the current native-integrated TurboAPI."""


TurboAPI = NativeIntegratedTurboAPI
