"""Release metadata regression tests."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
SETUP = ROOT / "python" / "setup.py"
PACKAGE_INIT = ROOT / "python" / "turboapi" / "__init__.py"


def _read_pyproject_version() -> str:
    data = tomllib.loads(PYPROJECT.read_text())
    return data["project"]["version"]


def _extract_string_assignment(path: Path, pattern: str) -> str:
    match = re.search(pattern, path.read_text())
    assert match, f"Could not find version pattern in {path}"
    return match.group(1)


def test_release_versions_are_in_sync():
    """Release metadata files must all declare the same package version."""
    pyproject_version = _read_pyproject_version()
    setup_version = _extract_string_assignment(SETUP, r'version="([^"]+)"')
    package_version = _extract_string_assignment(PACKAGE_INIT, r'__version__ = "([^"]+)"')

    assert pyproject_version == setup_version == package_version


def test_release_version_bumped_past_bad_1_0_25_publish():
    """This release must move past the broken 1.0.25/1.0.26 artifact publishes."""
    assert _read_pyproject_version() == "1.0.27"
