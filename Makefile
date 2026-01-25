.PHONY: help test build install clean benchmark

help:
	@echo "TurboAPI Development Commands"
	@echo "=============================="
	@echo ""
	@echo "Testing:"
	@echo "  make test          - Run all tests"
	@echo ""
	@echo "Building:"
	@echo "  make build         - Build wheel"
	@echo "  make install       - Install in development mode"
	@echo "  make clean         - Clean build artifacts"
	@echo ""
	@echo "Benchmarks:"
	@echo "  make benchmark     - Run benchmarks and generate charts"
	@echo ""

# Run tests
test:
	@echo "🧪 Running tests..."
	@python -m pytest tests/ -v --tb=short

# Build wheel
build:
	@echo "📦 Building wheel..."
	@maturin build --release

# Install in development mode
install:
	@echo "🔧 Installing in development mode..."
	@maturin develop --release

# Clean build artifacts
clean:
	@echo "🧹 Cleaning build artifacts..."
	@rm -rf target/
	@rm -rf dist/
	@rm -rf build/
	@rm -rf *.egg-info
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@find . -type f -name "*.so" -delete
	@echo "✅ Clean complete"

# Run benchmarks
benchmark:
	@echo "📊 Running benchmarks..."
	@PYTHON_GIL=0 python benchmarks/run_benchmarks.py
	@echo ""
	@echo "📈 Generating charts..."
	@python benchmarks/generate_charts.py
	@echo "✅ Benchmarks complete! Charts saved to assets/"
