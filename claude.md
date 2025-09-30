# TurboAPI Ruff Linting Issues - Full Report

**Total Issues: 50 errors**
**Date: 2025-10-01**
**Ruff Version: 0.13.2**

## Summary by Category

### 1. F401 - Unused Imports (2 errors)
- `check_free_threading_support` imported but unused in `__init__.py:10`
- `get_python_threading_info` imported but unused in `__init__.py:16`

### 2. W293 - Blank Lines with Whitespace (30 errors)
Multiple files have trailing whitespace on blank lines:
- `turboapi/app.py`: 18 occurrences
- `turboapi/version_check.py`: 12 occurrences

### 3. E721 - Type Comparisons (8 errors)
Using `==` or `!=` for type comparisons instead of `isinstance()` or `is`:
- `rust_integration.py:179` - `param.annotation == int`
- `rust_integration.py:181` - `param.annotation == float`  
- `rust_integration.py:183` - `param.annotation == bool`
- `server_integration.py:313` - `param_def.type != str`
- `server_integration.py:332` - `param.annotation == int`
- `server_integration.py:334` - `param.annotation == float`
- `server_integration.py:336` - `param.annotation == bool`

### 4. E722 - Bare Except Clauses (7 errors)
Using bare `except:` instead of specific exceptions:
- `version_check.py:113, 120, 131, 140, 148, 157, 163`

### 5. B007 - Unused Loop Variables (2 errors)
Loop control variables not used in loop body:
- `rust_integration.py:202` - `param` should be `_param`
- `server_integration.py:349` - `param` should be `_param`

### 6. B023 - Function Closure Issue (1 error)
- `rust_integration.py:243` - Function definition does not bind loop variable `rust_handler`

### 7. UP036 - Outdated Version Check (1 error)
- `version_check.py:61` - Version block `sys.version_info < (3, 13)` is outdated for minimum Python version

## Fixes Required

### Priority 1: Security & Correctness
1. **E722 - Replace bare except clauses** (7 fixes)
   - Change `except:` to `except Exception:` or specific exception types
   
2. **E721 - Fix type comparisons** (8 fixes)
   - Replace `param.annotation == int` with `param.annotation is int`
   - Or use `isinstance()` where appropriate

3. **B023 - Fix closure issue** (1 fix)
   - Bind `rust_handler` properly in closure

### Priority 2: Code Quality
4. **B007 - Rename unused loop variables** (2 fixes)
   - Change `param` to `_param` where not used
   
5. **F401 - Fix unused imports** (2 fixes)
   - Either use the imports or add them to `__all__`
   
6. **UP036 - Remove outdated version check** (1 fix)
   - Since minimum Python is 3.13, this check is redundant

### Priority 3: Style
7. **W293 - Remove trailing whitespace** (30 fixes)
   - Run `ruff format` to auto-fix

## Commands to Fix

```bash
# Auto-fix what's possible (whitespace, imports)
ruff check --fix turboapi/

# Format code
ruff format turboapi/

# Enable unsafe fixes (for type comparisons)
ruff check --fix --unsafe-fixes turboapi/
```

## Manual Fixes Required

Some issues need manual review:
- Type comparison changes (E721) should be carefully reviewed
- Bare except clauses (E722) should specify actual exception types
- Closure binding issue (B023) needs code refactoring

## Notes

- All whitespace issues (W293) can be auto-fixed
- Most issues are in `version_check.py`, `rust_integration.py`, and `server_integration.py`
- The project requires Python 3.13+, so some checks can be simplified
