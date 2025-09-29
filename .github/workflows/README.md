# TurboAPI GitHub Actions Workflows

This directory contains GitHub Actions workflows for building, testing, and releasing TurboAPI.

## Workflows

### 1. `ci.yml` - Continuous Integration
**Triggers:** Push to `main`/`develop`, Pull Requests to `main`

**What it does:**
- Tests Rust components (formatting, clippy, tests)
- Tests Python components (build, import tests)
- Builds wheels for all platforms
- Runs performance benchmarks

### 2. `build-wheels.yml` - Build and Publish Wheels
**Triggers:** Push to tags (`v*`), Manual dispatch

**What it does:**
- Builds wheels for all platforms (Linux x86_64/ARM64, macOS Intel/ARM, Windows)
- Tests wheel installation
- Publishes to PyPI
- Creates GitHub releases

### 3. `release.yml` - Release Process
**Triggers:** Manual dispatch with version bump selection

**What it does:**
- Bumps version in `python/pyproject.toml` and `Cargo.toml`
- Creates git tag
- Triggers wheel building workflow
- Updates documentation

### 4. `build-and-release.yml` - Streamlined Build and Release
**Triggers:** Push to tags (`v*`), Manual dispatch

**What it does:**
- All-in-one workflow for building and releasing
- Builds wheels for all platforms
- Tests installations
- Publishes to PyPI
- Creates GitHub releases with performance highlights

## Platform Support

### Supported Platforms
- **Linux:** x86_64, ARM64 (manylinux 2014)
- **macOS:** Intel (x86_64), Apple Silicon (ARM64)
- **Windows:** x64

### Python Version
- **Python 3.13+** (free-threading required for TurboAPI)

## Usage

### Creating a Release

#### Option 1: Manual Release Process
1. Go to Actions → "Release Process"
2. Click "Run workflow"
3. Select version bump type (patch/minor/major)
4. The workflow will:
   - Bump versions
   - Create and push git tag
   - Trigger wheel building
   - Publish to PyPI

#### Option 2: Tag-based Release
1. Create and push a version tag:
   ```bash
   git tag v2.0.1
   git push origin v2.0.1
   ```
2. The `build-and-release.yml` workflow will automatically:
   - Build wheels
   - Test installations
   - Publish to PyPI
   - Create GitHub release

### Testing Before Release
1. Use the manual dispatch option in `build-wheels.yml`
2. Set `test_pypi: true` to publish to Test PyPI first
3. Test the installation from Test PyPI

## Secrets Required

Add these secrets to your GitHub repository:

- `PYPI_API_TOKEN` - PyPI API token for publishing
- `TEST_PYPI_API_TOKEN` - Test PyPI API token (optional)

## Performance Highlights

The workflows automatically include performance benchmarks in release notes:
- **160K+ RPS** achieved in testing
- **5-10x faster** than FastAPI
- **True parallelism** with Python 3.13 free-threading
- **Zero Python middleware overhead**

## Troubleshooting

### Common Issues

1. **Python 3.13 not available:** The workflows use Python 3.13 which is required for TurboAPI's free-threading features.

2. **Maturin path issues:** All workflows use `--manifest-path python/pyproject.toml` to correctly locate the Python package.

3. **Wheel compatibility:** The workflows build wheels with proper platform tags for maximum compatibility.

### Debugging

- Check the Actions tab for detailed logs
- Wheel building failures are often due to missing system dependencies
- Import test failures indicate packaging issues

## Future Enhancements

- [ ] Add Python 3.14 support when available
- [ ] Add more comprehensive integration tests
- [ ] Add automated performance regression detection
- [ ] Add security scanning workflows
