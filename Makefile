.PHONY: help test build install release clean benchmark zig-test lint fmt hooks check \
       bump-patch bump-minor bump-major bump-beta version pre-release

RUFF ?= $(shell if command -v ruff >/dev/null 2>&1; then printf 'ruff'; elif [ -x .venv314t/bin/ruff ]; then printf '.venv314t/bin/ruff'; elif [ -x .venv/bin/ruff ]; then printf '.venv/bin/ruff'; elif command -v uv >/dev/null 2>&1; then printf 'uv run --extra dev ruff'; else printf 'ruff'; fi)

help:
	@echo "TurboAPI Development Commands"
	@echo "=============================="
	@echo ""
	@echo "Building:"
	@echo "  make build         - Build + install Zig backend (debug)"
	@echo "  make release       - Build + install Zig backend (ReleaseFast)"
	@echo "  make install       - Alias for build"
	@echo "  make clean         - Clean build artifacts"
	@echo ""
	@echo "Testing:"
	@echo "  make test          - Run all Python tests"
	@echo "  make zig-test      - Run Zig unit tests"
	@echo "  make check         - Lint + format check + Zig compile (what pre-commit runs)"
	@echo ""
	@echo "Code quality:"
	@echo "  make lint          - Run ruff linter on Python code"
	@echo "  make fmt           - Auto-format Python code with ruff"
	@echo ""
	@echo "Releasing:"
	@echo "  make bump-beta     - Bump to next beta (0.7.0b1 → 0.7.0b2)"
	@echo "  make bump-patch    - Bump patch version (0.7.0 → 0.7.1)"
	@echo "  make bump-minor    - Bump minor version (0.7.0 → 0.8.0)"
	@echo "  make bump-major    - Bump major version (0.7.0 → 1.0.0)"
	@echo "  make pre-release   - Run tests, bump beta, commit + tag + push"
	@echo "  make version       - Show current version"
	@echo ""
	@echo "Setup:"
	@echo "  make hooks         - Install git pre-commit hook"
	@echo ""
	@echo "Benchmarks:"
	@echo "  make benchmark     - Run benchmarks and generate charts"
	@echo ""

# ── Building ──────────────────────────────────────────────────────────────────

build:
	@./scripts/build.sh

release:
	@./scripts/build.sh --release

install: build

# ── Testing ───────────────────────────────────────────────────────────────────

test:
	@echo "🧪 Running tests..."
	@python -m pytest tests/ -v --tb=short

zig-test:
	@cd zig && zig build test

# ── Code quality ──────────────────────────────────────────────────────────────

lint:
	@$(RUFF) check python/ tests/ --no-fix

fmt:
	@$(RUFF) format python/ tests/
	@$(RUFF) check python/ tests/ --fix

check:
	@echo "🔍 Running pre-commit checks..."
	@$(RUFF) check python/ tests/ --no-fix
	@$(RUFF) format python/ tests/ --check
	@./scripts/build.sh --check
	@echo "✅ All checks passed"

# ── Setup ─────────────────────────────────────────────────────────────────────

hooks:
	@echo "🔗 Installing pre-commit hook..."
	@cp scripts/pre-commit .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "✅ Pre-commit hook installed"
	@echo "   Runs: ruff lint+format on .py, zig build check on .zig"
	@echo "   Bypass: git commit --no-verify"

# ── Clean ─────────────────────────────────────────────────────────────────────

clean:
	@echo "🧹 Cleaning build artifacts..."
	@rm -rf zig/zig-out/ zig/.zig-cache/
	@rm -rf dist/ build/ *.egg-info
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@find python/turboapi -name "*.so" -delete 2>/dev/null || true
	@echo "✅ Clean complete"

# ── Benchmarks ────────────────────────────────────────────────────────────────

benchmark:
	@echo "📊 Running benchmarks..."
	@PYTHON_GIL=0 python benchmarks/run_benchmarks.py
	@echo ""
	@echo "📈 Generating charts..."
	@python benchmarks/generate_charts.py
	@echo "✅ Benchmarks complete! Charts saved to assets/"

# ── Versioning & Release ─────────────────────────────────────────────────────

version:
	@grep -m1 'version' pyproject.toml | sed 's/.*"\(.*\)"/\1/'

bump-patch:
	@./scripts/bump-version.sh patch

bump-minor:
	@./scripts/bump-version.sh minor

bump-major:
	@./scripts/bump-version.sh major

bump-beta:
	@./scripts/bump-version.sh beta

pre-release: check
	@echo ""
	@echo "🚀 Preparing pre-release..."
	@./scripts/bump-version.sh beta
	@VERSION=$$(grep -m1 'version' pyproject.toml | sed 's/.*"\(.*\)"/\1/') && \
		echo "   Version: $$VERSION" && \
		git add pyproject.toml && \
		git commit -m "pre-release: v$$VERSION" && \
		git tag "v$$VERSION" && \
		echo "" && \
		echo "✅ Tagged v$$VERSION" && \
		echo "   Push with: git push && git push --tags" && \
		echo "   This will trigger the Build & Publish workflow on GitHub"
