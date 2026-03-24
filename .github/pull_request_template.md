## Linked Issue

Closes #

If this PR is not tied to an existing issue, open one first.

## Summary

- what changed
- why it changed
- what is intentionally not in scope

## Scope

- subsystems touched:
- generated files changed: yes/no
- lockfile changed: yes/no
- benchmark/docs-only/runtime change:

## Rebase Status

- [ ] Rebasing onto current `main` completed before requesting review

## Tests Run

```bash
# paste exact commands here
```

## Benchmarks

If this PR changes benchmark code or benchmark claims, fill this out:

- layer measured: driver-only / HTTP-only / end-to-end HTTP+DB
- caches disabled or enabled:
- warmup policy:
- number of runs:
- local or CI:
- environment:

## Checklist

- [ ] PR is matched to an issue
- [ ] PR scope is narrow and reviewable
- [ ] No generated `.zig-cache`, `zig-out`, dylibs, or other build artifacts are committed
- [ ] No unrelated dependency or `uv.lock` churn is included
- [ ] Docs/benchmarks were updated only if the code change actually requires it
