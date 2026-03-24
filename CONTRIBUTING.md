# Contributing

Thanks for contributing to TurboAPI.

This codebase moves quickly and spans Python, Zig, benchmarks, and generated native artifacts. Small, current, issue-linked PRs are much easier to review and much less likely to regress behavior.

## Ground Rules

1. Every PR must be tied to an issue.
2. Rebase onto current `main` before requesting final review.
3. Keep PRs tightly scoped.
4. Do not commit generated artifacts.
5. Do not mix unrelated lockfile churn into bug-fix or perf PRs.

If a branch goes stale, close it and open a smaller replacement instead of accreting more changes onto the old PR.

See also: issue [#81](https://github.com/justrach/turboAPI/issues/81) for the process discussion around stale PRs in a fast-changing codebase.

## PR Requirements

Every PR description should include:

- linked issue number
- summary of the exact change
- files or subsystems touched
- tests run
- whether the branch was rebased onto current `main`
- whether any generated files, lockfiles, or benchmarks changed

If a PR does not map cleanly to an issue, open the issue first.

## Scope Rules

Good PR scope:

- one bug fix
- one benchmark methodology fix
- one small perf change
- one docs-only clarification

Bad PR scope:

- runtime change + unrelated refactor
- perf tweak + dependency upgrade
- feature work + generated `.zig-cache` / `zig-out` output
- benchmark change + marketing/docs rewrite + lockfile churn

If a reviewer cannot explain the PR in one sentence, it is probably too large.

## Rebase Policy

Before requesting review on any non-trivial PR:

```bash
git fetch origin
git rebase origin/main
```

Why this matters:

- stale cleanup PRs can delete code that is no longer dead
- stale bug-fix PRs often miss newer behavior in `main`
- stale perf PRs become impossible to evaluate fairly

If rebasing reveals unrelated conflicts, split the PR.

## Generated Files

Do not commit generated or local-build artifacts, including:

- `.zig-cache/`
- `zig-out/`
- `.dylib`, `.so`, `.o`
- local benchmark artifacts/logs unless the PR is explicitly about publishing benchmark evidence

If a file is generated during local builds, add or update `.gitignore` instead of committing it.

## Lockfiles And Dependencies

Do not update `uv.lock` unless the PR actually changes Python dependencies.

If you touch dependency metadata:

- explain why
- keep that change isolated
- mention it clearly in the PR summary

Perf or cleanup PRs should not silently widen the dependency surface.

## Tests

At minimum, run the narrowest relevant tests for the code you changed.

Examples:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv314t/bin/python -m pytest -q tests/test_annotated_depends.py
```

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv314t/bin/python -m pytest -q tests/test_turbopg.py
```

```bash
zig build test
```

If you changed benchmarks:

- state whether the run was local or CI
- include exact machine/environment details
- do not mix local Apple Silicon numbers with GitHub Actions Ubuntu numbers

## Benchmark PRs

Benchmark-related PRs must say:

- what layer is being measured
  - driver-only
  - HTTP-only
  - end-to-end HTTP+DB
- whether caches are on or off
- whether numbers are cold-start or warmed steady-state
- number of runs
- whether values are single-run or median

Do not publish cached results as uncached DB performance.

## Review Expectations

Reviewers will push back on:

- stale branches
- unrelated file churn
- generated artifacts
- oversized PRs
- missing issue links
- claims that do not match the changed code

That is process, not hostility.

The easiest way to get a fast review is:

1. open an issue
2. make a small branch
3. rebase onto `main`
4. keep the diff narrow
5. include exact tests and rationale
