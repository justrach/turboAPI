---
name: turbo-test
description: Run TurboAPI tests. Use when running tests, checking for regressions, or verifying changes.
disable-model-invocation: true
argument-hint: [file-or-pattern]
---

# Run TurboAPI Tests

## Steps

1. **Determine scope**: If `$ARGUMENTS` is provided, run only matching tests. Otherwise run the full suite.

2. **Run tests**:

```bash
# Full suite
uv run --python 3.14t python -m pytest tests/ -p no:anchorpy \
  --deselect tests/test_fastapi_parity.py::TestWebSocket -v

# Specific file
uv run --python 3.14t python -m pytest tests/$ARGUMENTS -v

# Specific test
uv run --python 3.14t python -m pytest tests/ -k "$ARGUMENTS" -v
```

3. **Run Zig unit tests** (if Zig files changed):

```bash
cd zig && zig build test
```

4. **Run continuous fuzzing** (if security-sensitive changes):

```bash
cd zig && zig build test --fuzz
```

## Known exclusions

- **WebSocket tests** (`TestWebSocket`) — pre-existing failure, always deselect
- **anchorpy plugin** — causes import error, disable with `-p no:anchorpy`

## Test categories

| File | What it tests |
|------|--------------|
| `test_fastapi_parity.py` | FastAPI compatibility (275+ tests) |
| `test_security_audit_fixes.py` | Security fixes (rate limiting, CORS, etc.) |
| `test_annotated_depends.py` | Annotated[Type, Depends(...)] pattern |
| `test_perf_callnoargs_tupleabi.py` | Handler classification + fast paths |
| `test_query_and_headers.py` | Query params, headers, body parsing |

## Quick smoke test

```bash
uv run --python 3.14t python -c "
from turboapi import TurboAPI
app = TurboAPI()
@app.get('/')
def hello(): return {'ok': True}
from turboapi.testclient import TestClient
c = TestClient(app)
assert c.get('/').status_code == 200
print('OK')
"
```
