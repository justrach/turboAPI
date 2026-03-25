---
name: hotfix-adversary
description: Use when preparing or reviewing a hotfix/bugfix branch. Requires an exact repro or focused regression test, an adversarial review pass, and explicit verification evidence before opening or merging the PR.
---

# Hotfix Adversary

Use this skill on any branch named `hotfix/*` or `bugfix/*`, or when the user asks for a bug-fix release or emergency patch.

## Required workflow

1. Identify the exact bug claim.
2. Add or update one focused regression test or exact repro.
3. Run the smallest relevant test command first.
4. Run an adversarial review pass with gitagent before merge.
5. Only then open or update the PR.

## Adversarial review

Use any available gitagent reviewer or reviewer-fixer workflow in the current environment.
Examples, when available, include a dedicated reviewer pass, a review-fix loop, or a reviewer-oriented task preset.

The adversarial pass should look for:

- false positives where the “fix” only changes tests
- hidden regressions in adjacent request/response paths
- incomplete edge handling
- versioning or release metadata drift
- benchmark or verification claims that are not supported by the test evidence

## Hotfix acceptance bar

Do not call the hotfix done unless all are true:

- the exact repro now passes
- the adversarial review found no remaining blocking issue, or its findings were fixed and rechecked
- the PR body states what changed, how it was verified, and what was intentionally not changed

## Keep it narrow

- Do not bundle unrelated refactors.
- Do not include unrelated dirty-worktree files in the branch.
- Prefer a patch version bump only.
