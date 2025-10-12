# TurboAPI Testing Guide 🧪

Comprehensive testing workflow to ensure package integrity before releases.

## Quick Start

```bash
# Run quick tests (recommended before every commit)
make test-quick

# Run full test suite (before releases)
make test-full

# Or use the test script directly
python test_package_integrity.py
```

## Test Suite

### 1. **Quick Tests** (< 5 seconds)
```bash
make test-quick
```

Validates:
- ✅ Rust module (`turbonet`) imports correctly
- ✅ TurboAPI main class works
- ✅ Basic functionality operational

**Run this before every commit!**

### 2. **Full Test Suite** (~ 30 seconds)
```bash
make test-full
# or
python test_package_integrity.py
```

Validates:
- ✅ Local development install works
- ✅ Rust module imports correctly
- ✅ Basic TurboAPI functionality
- ✅ Wheel builds successfully
- ✅ Rust module is bundled in wheel
- ✅ Wheel installs in fresh venv
- ✅ Imports work after wheel install

**Run this before creating releases!**

## What Each Test Does

### Test 1: Local Development Install
```bash
cd python && maturin develop --release
```
Ensures the package builds correctly in development mode.

### Test 2: Rust Module Import
```python
from turboapi import turbonet
assert hasattr(turbonet, 'TurboServer')
```
Verifies the Rust core is accessible from Python.

### Test 3: Basic Functionality
```python
from turboapi import TurboAPI
app = TurboAPI()

@app.get("/test")
def test():
    return {"ok": True}
```
Tests that routes can be registered and basic API works.

### Test 4: Wheel Build
```bash
maturin build --release
unzip -l turboapi-*.whl | grep turbonet
```
Builds a wheel and verifies the Rust module is included.

### Test 5: Wheel Install in Venv
```bash
python -m venv test_venv
test_venv/bin/pip install turboapi-*.whl
test_venv/bin/python -c "from turboapi import turbonet"
```
Creates a fresh virtual environment and tests installation from wheel.

## Pre-Release Checklist

Before creating a new release:

```bash
# 1. Run full test suite
make test-full

# 2. Update version numbers
# Edit: Cargo.toml and python/pyproject.toml

# 3. Commit changes
git add -A
git commit -m "release: v0.X.X"

# 4. Create tag
git tag -a v0.X.X -m "Release v0.X.X"

# 5. Push to GitHub
git push origin main
git push origin v0.X.X
```

## Common Issues

### Issue: "Rust core not available"
**Cause**: Rust module not bundled in wheel  
**Fix**: Check `python/pyproject.toml` - ensure `module-name = "turboapi.turbonet"`

### Issue: Import error after pip install
**Cause**: Module path mismatch  
**Fix**: Verify import statement: `from turboapi import turbonet`

### Issue: Wheel build fails
**Cause**: Maturin configuration issue  
**Fix**: Check `[tool.maturin]` section in `python/pyproject.toml`

## CI/CD Integration

The test suite is designed to run in CI/CD pipelines:

```yaml
# .github/workflows/test.yml
- name: Test Package Integrity
  run: |
    pip install maturin
    python test_package_integrity.py
```

## Development Workflow

**Recommended workflow:**

1. **Make changes** to code
2. **Run quick tests**: `make test-quick`
3. **Commit** if tests pass
4. **Before release**: `make test-full`
5. **Tag and push** if all tests pass

## Makefile Commands

```bash
make help          # Show all available commands
make test-quick    # Quick tests (< 5s)
make test-full     # Full test suite (~ 30s)
make build         # Build wheel
make install       # Install in dev mode
make clean         # Clean build artifacts
make release       # Pre-release checks
```

## Manual Testing

If you prefer manual testing:

```bash
# 1. Build in dev mode
cd python && maturin develop --release

# 2. Test import
python -c "from turboapi import turbonet; print('OK')"

# 3. Build wheel
maturin build --release

# 4. Check wheel contents
unzip -l target/wheels/turboapi-*.whl | grep turbonet

# 5. Test in fresh venv
python -m venv test_venv
test_venv/bin/pip install target/wheels/turboapi-*.whl
test_venv/bin/python -c "from turboapi import TurboAPI"
```

## Performance Testing

For performance benchmarks:

```bash
# Run benchmark suite
python archive/benchmark_v040.py

# Compare with FastAPI
python archive/benchmark_turboapi_vs_fastapi.py
```

## Questions?

- **Quick test failed?** Check if you ran `maturin develop` recently
- **Wheel test failed?** Verify `module-name` in `pyproject.toml`
- **Import error?** Ensure Rust toolchain is installed

---

**Remember**: Always run `make test-quick` before committing! 🚀
