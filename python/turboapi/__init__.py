"""
TurboAPI - Revolutionary Python web framework
Requires Python 3.13+ free-threading for maximum performance
"""

# Check free-threading compatibility FIRST (before any other imports)
from .version_check import check_free_threading_support

from .rust_integration import TurboAPI
from .routing import Router, APIRouter
from .models import TurboRequest, TurboResponse

__version__ = "2.0.0"
__all__ = ["TurboAPI", "APIRouter", "Router", "TurboRequest", "TurboResponse"]

# Additional exports for free-threading diagnostics
from .version_check import get_python_threading_info

__all__.extend(["get_python_threading_info"])
