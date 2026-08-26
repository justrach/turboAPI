"""Release metadata regression tests."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
SETUP = ROOT / "python" / "setup.py"
PACKAGE_INIT = ROOT / "python" / "turboapi" / "__init__.py"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


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
    """This release must move past the broken 1.0.25/1.0.26 artifact publishes.

    Compares as a tuple of integers so the guard keeps holding through
    future patch / minor / major bumps without needing per-release edits.
    """
    version = _read_pyproject_version()
    parts = tuple(int(p) for p in version.split(".")[:3])
    assert parts >= (1, 0, 27), (
        f"version {version} must be >= 1.0.27 (skipping the broken "
        f"1.0.25 / 1.0.26 publishes)"
    )


def test_stable_release_dispatches_build_at_created_tag():
    """Workflow-token tag pushes need an explicit tag-ref build dispatch."""
    workflow = RELEASE_WORKFLOW.read_text()
    release_job = workflow.split("\n  release:\n", 1)[1]
    release_permissions = release_job.split("\n    steps:\n", 1)[0]

    assert "      actions: write\n" in release_permissions
    assert 'gh workflow run build-and-release.yml --ref "v${VERSION}"' in release_job
    assert "gh workflow run build-and-release.yml --ref main" not in release_job
