# TurboAPI v0.3.1 Release Notes

**Release Date**: 2025-10-01  
**Type**: Critical Packaging Fix

## 🐛 Bug Fixes

### Fixed PyPI Source Distribution Packaging
**Issue**: Version 0.3.0 had a broken source distribution on PyPI. When users tried to install via `pip install turboapi==0.3.0`, they encountered:

```
Failed to read readme specified in pyproject.toml, which should be at
/private/var/.../src/../README.md
Caused by: failed to open file: No such file or directory (os error 2)
```

**Root Cause**: The `[tool.maturin]` configuration in `pyproject.toml` didn't include the `README.md` and `LICENSE` files in the source distribution.

**Solution**: Updated `pyproject.toml` to explicitly include these files:

```toml
[tool.maturin]
python-source = "."
module-name = "turboapi._rust"
manifest-path = "../Cargo.toml"
include = [
    "turboapi/**/*.py",
    "../README.md",      # ← Added
    "../LICENSE",        # ← Added
]
```

## 📦 Changes

### Version Bumps
- `python/pyproject.toml`: `0.3.0` → `0.3.1`
- `Cargo.toml`: `0.3.0` → `0.3.1`

### Package Manifest
- ✅ Now properly includes `README.md` in source distribution
- ✅ Now properly includes `LICENSE` in source distribution
- ✅ Wheels are unaffected (they were working fine)

## ✅ Verification

After this release, users should be able to install from PyPI without errors:

```bash
pip install turboapi==0.3.1
# or
pip install turboapi  # latest version
```

The source distribution will now build correctly because all required files are included.

## 🔄 Migration from v0.3.0

### If You Had v0.3.0 Installed Successfully
You were likely using pre-built wheels, which worked fine. You can upgrade to v0.3.1 for consistency:

```bash
pip install --upgrade turboapi
```

### If v0.3.0 Installation Failed
This release fixes your issue! Simply install v0.3.1:

```bash
pip install turboapi==0.3.1
```

## 📝 No API Changes

This is purely a packaging fix. There are:
- ❌ No API changes
- ❌ No breaking changes
- ❌ No feature additions
- ✅ Only packaging improvements

All code from v0.3.0 remains the same.

## 🚀 Features (Unchanged from v0.3.0)

- Python 3.13+ free-threading support
- FastAPI-compatible syntax
- 180,000+ RPS performance
- Rust-powered HTTP core
- Rate limiting (configurable)
- 25x faster than FastAPI in high-concurrency scenarios

## 📚 Documentation

- [Installation Guide](README.md#installation)
- [Quick Start](README.md#quick-start)
- [Python 3.13 Free-Threading Setup](PYTHON_313_FREE_THREADING_SETUP.md)
- [AI Agent Integration](AGENTS.md)

## 🙏 Acknowledgments

Thanks to users who reported the PyPI installation issue!

## 🔗 Links

- **GitHub**: https://github.com/justrach/turboAPI
- **PyPI**: https://pypi.org/project/turboapi/
- **Tag**: v0.3.1
