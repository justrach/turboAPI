.PHONY: help test build install clean benchmark zig-test

help:
	@echo "TurboAPI Development Commands"
	@echo "=============================="
	@echo ""
	@echo "Testing:"
	@echo "  make test          - Run all tests"
	@echo "  make zig-test      - Run Zig unit tests"
	@echo ""
	@echo "Building:"
	@echo "  make build         - Build + install Zig backend for current Python"
	@echo "  make install       - Alias for build"
	@echo "  make clean         - Clean build artifacts"
	@echo ""
	@echo "Benchmarks:"
	@echo "  make benchmark     - Run benchmarks and generate charts"
	@echo ""

# Run tests
test:
	@echo "🧪 Running tests..."
	@python -m pytest tests/ -v --tb=short

# Build + install Zig backend (auto-detects Python version + free-threading)
build:
	@python zig/build_turbonet.py --install

# Alias
install: build

# Run Zig unit tests
zig-test:
	@cd zig && zig build test

# Clean build artifacts
clean:
	@echo "🧹 Cleaning build artifacts..."
	@rm -rf zig/zig-out/ zig/.zig-cache/
	@rm -rf dist/ build/ *.egg-info
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@find python/turboapi -name "*.so" -delete 2>/dev/null || true
	@echo "✅ Clean complete"

# Run benchmarks
benchmark:
	@echo "📊 Running benchmarks..."
	@PYTHON_GIL=0 python benchmarks/run_benchmarks.py
	@echo ""
	@echo "📈 Generating charts..."
	@python benchmarks/generate_charts.py
	@echo "✅ Benchmarks complete! Charts saved to assets/"
