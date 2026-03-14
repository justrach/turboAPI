# TurboAPI GitHub Actions Workflows

## Workflows

### `ci.yml` — Continuous Integration
**Triggers:** Push to `main`/`feature/zig-backend`, PRs to `main`

Runs tests across Python 3.13, 3.14, and 3.14t (free-threaded) on Ubuntu and macOS. Also runs Zig unit tests and a thread-safety stress test.

### `pre-release.yml` — Beta Release
**Triggers:** Push to `feature/zig-backend`, manual dispatch

1. Runs the full test matrix
2. Auto-computes a beta version from commit count (e.g. `0.7.0b12`)
3. Builds an sdist and publishes to PyPI as a pre-release

Install a beta: `pip install turboapi==0.7.0b1`

### `release.yml` — Stable Release
**Triggers:** Manual dispatch (choose patch/minor/major)

1. Runs the full test matrix
2. Bumps version in `pyproject.toml`
3. Commits, tags (`v0.7.0`), and pushes
4. Builds wheels for all platform × Python combos
5. Publishes to PyPI + creates GitHub Release

### `build-and-release.yml` — Tag-triggered Build & Publish
**Triggers:** Push tag `v*`

Fallback for manual `git tag v0.7.0b3 && git push --tags`. Detects pre-release tags (containing `a`, `b`, `rc`, `dev`) and marks the GitHub Release accordingly.

### `benchmark.yml` — Performance Benchmarks
**Triggers:** Push to `main`, PRs to `main`, manual dispatch

Runs TurboAPI vs FastAPI benchmarks with `wrk`. Posts results as a PR comment.

## Release Flow

```
feature/zig-backend ──push──→ pre-release.yml ──→ PyPI 0.7.0b1 (beta)
                     ──push──→ pre-release.yml ──→ PyPI 0.7.0b2 (beta)
                     ──PR──→ main
main                          release.yml (manual) ──→ PyPI 0.7.0 (stable)
```

### Local release commands

```bash
make version        # show current version
make bump-beta      # 0.7.0 → 0.7.0b1, 0.7.0b1 → 0.7.0b2
make bump-patch     # 0.7.0 → 0.7.1
make bump-minor     # 0.7.0 → 0.8.0
make bump-major     # 0.7.0 → 1.0.0
make pre-release    # run checks, bump beta, commit, tag (then push)
```

## Secrets Required

- `PYPI_API_TOKEN` — PyPI API token for publishing
- `GITHUB_TOKEN` — auto-provided by GitHub Actions

## Platform × Python Matrix

| Platform | Python 3.13 | Python 3.14 | Python 3.14t |
|----------|:-----------:|:-----------:|:------------:|
| Ubuntu   | ✅          | ✅          | ✅           |
| macOS    | ✅          | ✅          | ✅           |
