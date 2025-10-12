.PHONY: help test test-quick test-full build install clean release

help:
	@echo "TurboAPI Development Commands"
	@echo "=============================="
	@echo ""
	@echo "Testing:"
	@echo "  make test          - Run package integrity tests (recommended before commit)"
	@echo "  make test-quick    - Run quick tests (import + basic functionality)"
	@echo "  make test-full     - Run all tests including wheel build"
	@echo ""
	@echo "Building:"
	@echo "  make build         - Build wheel"
	@echo "  make install       - Install in development mode"
	@echo "  make clean         - Clean build artifacts"
	@echo ""
	@echo "Release:"
	@echo "  make release       - Run full test suite before release"
	@echo ""

# Quick tests (fast, run before every commit)
test-quick:
	@echo "🚀 Running quick integrity tests..."
	@python3 -c "from turboapi import turbonet; print('✅ Rust module imports')"
	@python3 -c "from turboapi import TurboAPI; app = TurboAPI(); print('✅ TurboAPI works')"
	@echo "✅ Quick tests passed!"

# Full test suite (run before releases)
test-full:
	@echo "🧪 Running full package integrity test suite..."
	@python3 test_package_integrity.py

# Default test (quick + wheel check)
test:
	@echo "🧪 Running package integrity tests..."
	@python3 test_package_integrity.py

# Build wheel
build:
	@echo "📦 Building wheel..."
	@cd python && maturin build --release

# Install in development mode
install:
	@echo "🔧 Installing in development mode..."
	@cd python && maturin develop --release

# Clean build artifacts
clean:
	@echo "🧹 Cleaning build artifacts..."
	@rm -rf target/
	@rm -rf python/target/
	@rm -rf python/dist/
	@rm -rf python/build/
	@rm -rf python/*.egg-info
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@find . -type f -name "*.so" -delete
	@echo "✅ Clean complete"

# Pre-release checks
release: test-full
	@echo ""
	@echo "✅ All tests passed! Ready for release."
	@echo ""
	@echo "Next steps:"
	@echo "  1. Update version in Cargo.toml and python/pyproject.toml"
	@echo "  2. git add -A && git commit -m 'release: vX.X.X'"
	@echo "  3. git tag -a vX.X.X -m 'Release vX.X.X'"
	@echo "  4. git push origin main && git push origin vX.X.X"
	@echo ""
