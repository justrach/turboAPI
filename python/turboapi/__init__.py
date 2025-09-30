"""
TurboAPI - Revolutionary Python web framework
Requires Python 3.13+ free-threading for maximum performance
"""

# Check free-threading compatibility FIRST (before any other imports)
from .models import TurboRequest, TurboResponse
from .routing import APIRouter, Router
from .rust_integration import TurboAPI
from .version_check import check_free_threading_support

__version__ = "2.0.0"
__all__ = [
    "TurboAPI",
    "APIRouter",
    "Router",
    "TurboRequest",
    "TurboResponse",
    "check_free_threading_support",
    "get_python_threading_info",
]

# Additional exports for free-threading diagnostics
from .version_check import get_python_threading_info
