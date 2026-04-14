"""
NUSMods helper app — links the local nusmods clone to the public NUSMods API.

Prerequisite: clone the repo next to this file's project root (default: ../nusmods):

    git clone https://github.com/nusmodifications/nusmods.git

Run (from the **turboAPI repo root** so `turboapi` and `examples/` resolve):

    uv run --python 3.14t python examples/nusmods_app.py

This uses the **TurboAPI** package from this repo (`from turboapi import ...`). The HTTP server
prefers the Zig backend (`turbonet`). If that is not built, the script falls back to **uvicorn**
(ASGI) so localhost still works — install dev deps: ``uv pip install -e ".[dev]"``.

Build the native core (optional, for full Zig performance):

    python zig/build_turbonet.py --install

API shape matches NUSMods v2 URLs (see nusmods/website/src/apis/nusmods.js).
"""

from __future__ import annotations

import html
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from turboapi import HTMLResponse, HTTPException, TurboAPI

GITHUB_REPO_HTTPS = "https://github.com/nusmodifications/nusmods.git"
NUSMODS_API_BASE = "https://api.nusmods.com/v2"

# Project root = parent of examples/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_NUSMODS_DIR = _PROJECT_ROOT / "nusmods"
_APP_CONFIG = _NUSMODS_DIR / "website" / "src" / "config" / "app-config.json"
_WEBSITE_PKG = _NUSMODS_DIR / "website" / "package.json"


def _acad_year_segment(academic_year: str) -> str:
    """Turn '2025/2026' or '2025-2026' into API path segment '2025-2026'."""
    s = academic_year.strip().replace("/", "-")
    if len(s) != 9 or s[4] != "-":
        raise HTTPException(status_code=400, detail="academic_year must look like 2025-2026 or 2025/2026")
    return s


def _default_academic_year() -> str:
    if _APP_CONFIG.is_file():
        with open(_APP_CONFIG, encoding="utf-8") as f:
            raw = json.load(f).get("academicYear", "2025/2026")
        return _acad_year_segment(raw)
    return "2025-2026"


def _fetch_json(url: str, timeout: float = 45.0) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "TurboAPI-nusmods-app/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            return json.loads(body)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:2000]
        raise HTTPException(status_code=e.code, detail=f"Upstream API error: {detail}") from e
    except urllib.error.URLError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach NUSMods API: {e}") from e
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"Invalid JSON from API: {e}") from e


def _repo_meta() -> dict:
    meta: dict = {
        "github_repo_git": GITHUB_REPO_HTTPS,
        "github_repo_web": "https://github.com/nusmodifications/nusmods",
        "local_clone_path": str(_NUSMODS_DIR),
        "local_clone_present": _NUSMODS_DIR.is_dir(),
        "website": "https://nusmods.com",
        "public_api": "https://api.nusmods.com/v2",
        "default_academic_year": _default_academic_year(),
    }
    if _WEBSITE_PKG.is_file():
        with open(_WEBSITE_PKG, encoding="utf-8") as f:
            pkg = json.load(f)
        meta["website_package_name"] = pkg.get("name")
        meta["website_package_version"] = pkg.get("version")
    return meta


app = TurboAPI(
    title="NUSMods (TurboAPI)",
    version="1.0.0",
    description="Browse NUSMods project info and query the official NUSMods v2 API.",
)


@app.get("/")
def home():
    m = _repo_meta()
    year = m["default_academic_year"]
    path_note = (
        '<span class="ok">local clone found</span>'
        if m["local_clone_present"]
        else f'<span class="warn">local clone not found at {html.escape(m["local_clone_path"])}</span>'
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>NUSMods via TurboAPI</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 52rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
    code {{ background: #f4f4f5; padding: 0.1em 0.35em; border-radius: 4px; }}
    a {{ color: #2563eb; }}
    ul {{ padding-left: 1.2rem; }}
    .ok {{ color: #15803d; }} .warn {{ color: #b45309; }}
  </style>
</head>
<body>
  <h1>NUSMods via TurboAPI</h1>
  <p>
    Linked upstream: <a href="{m["github_repo_web"]}">nusmodifications/nusmods</a>
    ({path_note}).
  </p>
  <h2>Quick links</h2>
  <ul>
    <li><a href="https://nusmods.com">nusmods.com</a> — main site</li>
    <li><a href="https://api.nusmods.com/v2">api.nusmods.com/v2</a> — public API</li>
    <li><a href="/api/nusmods/meta">GET /api/nusmods/meta</a> — JSON metadata (clone + defaults)</li>
  </ul>
  <h2>Try the API (default year {year})</h2>
  <ul>
    <li><a href="/api/nusmods/module-list?academic_year={year}">Module list (condensed)</a></li>
    <li><a href="/api/nusmods/modules/CS1101S?academic_year={year}">Module detail: CS1101S</a></li>
    <li><a href="/api/nusmods/venues?semester=1&academic_year={year}">Venues (semester 1)</a></li>
  </ul>
  <p>OpenAPI-style routes are listed in the JSON from <code>/api/nusmods/meta</code>.</p>
</body>
</html>"""
    return HTMLResponse(page)


@app.get("/api/nusmods/meta")
def nusmods_meta():
    """Project links, local clone status, and default academic year from the clone's app-config."""
    return _repo_meta()


@app.get("/api/nusmods/module-list")
def nusmods_module_list(academic_year: str | None = None):
    """Proxy: full condensed module list for an academic year (moduleList.json)."""
    year = _acad_year_segment(academic_year) if academic_year else _default_academic_year()
    url = f"{NUSMODS_API_BASE}/{year}/moduleList.json"
    return _fetch_json(url)


@app.get("/api/nusmods/module-information")
def nusmods_module_information(academic_year: str | None = None):
    """Proxy: moduleInformation.json (full module index for the year)."""
    year = _acad_year_segment(academic_year) if academic_year else _default_academic_year()
    url = f"{NUSMODS_API_BASE}/{year}/moduleInformation.json"
    return _fetch_json(url)


@app.get("/api/nusmods/modules/{module_code}")
@app.get("/api/nusmods/modules")
def nusmods_module_detail(module_code: str | None = None, academic_year: str | None = None):
    """Proxy: single module JSON (e.g. CS1101S)."""
    if not module_code:
        raise HTTPException(
            status_code=400,
            detail="module_code is required (use /api/nusmods/modules/{module_code} or ?module_code=CS1101S)",
        )
    code = module_code.strip().upper()
    if not code.replace(" ", "").isalnum():
        raise HTTPException(status_code=400, detail="invalid module_code")
    year = _acad_year_segment(academic_year) if academic_year else _default_academic_year()
    url = f"{NUSMODS_API_BASE}/{year}/modules/{code}.json"
    return _fetch_json(url)


@app.get("/api/nusmods/venues")
def nusmods_venues(semester: int, academic_year: str | None = None):
    """Proxy: venueInformation.json for a semester (1–4)."""
    if semester < 1 or semester > 4:
        raise HTTPException(status_code=400, detail="semester must be 1–4")
    year = _acad_year_segment(academic_year) if academic_year else _default_academic_year()
    url = f"{NUSMODS_API_BASE}/{year}/semesters/{semester}/venueInformation.json"
    return _fetch_json(url)


@app.get("/api/nusmods/venue-list")
def nusmods_venue_list(semester: int, academic_year: str | None = None):
    """Proxy: venues.json for a semester."""
    if semester < 1 or semester > 4:
        raise HTTPException(status_code=400, detail="semester must be 1–4")
    year = _acad_year_segment(academic_year) if academic_year else _default_academic_year()
    url = f"{NUSMODS_API_BASE}/{year}/semesters/{semester}/venues.json"
    return _fetch_json(url)


def main() -> None:
    """Start the app: Zig `app.run()` when `turbonet` is available, else uvicorn ASGI."""
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8010"))

    print(f"Local NUSMods clone: {_NUSMODS_DIR} ({'ok' if _NUSMODS_DIR.is_dir() else 'missing'})")

    try:
        from turboapi.native_integration import NATIVE_CORE_AVAILABLE
    except ImportError:
        NATIVE_CORE_AVAILABLE = False

    if NATIVE_CORE_AVAILABLE:
        print(f"Starting Zig HTTP server — open http://{host}:{port}/")
        app.run(host=host, port=port)
        return

    print(
        "[nusmods_app] Zig backend (turbonet) not available — using uvicorn ASGI.\n"
        "  To use the native server instead: python zig/build_turbonet.py --install\n"
        "  Requires uvicorn (included in .[dev]): uv pip install -e \".[dev]\"",
        file=sys.stderr,
    )
    try:
        import uvicorn
    except ImportError as e:
        print(
            "\nCould not import uvicorn. Install with:\n"
            '  uv pip install "uvicorn[standard]"\n'
            "or dev extras:\n"
            '  uv pip install -e ".[dev]"',
            file=sys.stderr,
        )
        raise SystemExit(1) from e

    print(f"Starting uvicorn — open http://{host}:{port}/")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
