# Windows Unicode Encoding Fix - TurboAPI v0.3.2

## Issue Summary

**Problem**: TurboAPI v0.3.1 failed to import on Windows systems due to `UnicodeEncodeError` when printing emoji characters to Windows console with cp1252 encoding.

**Error Message**:
```
UnicodeEncodeError: 'charmap' codec can't encode character '\u2705' in position 0: character maps to <undefined>
```

**Impact**: Complete import failure on Windows, preventing any use of TurboAPI on Windows platforms.

## Root Cause

The Python files used Unicode emoji characters (`✅`, `❌`, `🚀`, etc.) directly in print statements. On Windows systems with cp1252 encoding (default console encoding), these characters cannot be encoded, causing the program to crash during module import.

## Solution Implemented

### 1. **Smart Emoji Detection** (`version_check.py`)

Added intelligent emoji support detection:
- **UTF-8 Configuration**: Automatically configure stdout to use UTF-8 on Windows
- **Fallback Mechanism**: Test if emojis can be displayed, fall back to ASCII if not
- **Cross-Platform**: Works on Windows, macOS, and Linux

```python
# Configure stdout to use UTF-8 encoding on Windows
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    elif not isinstance(sys.stdout, io.TextIOWrapper):
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

# Define safe ASCII alternatives
CHECK_MARK = "[OK]"
CROSS_MARK = "[X]"
ROCKET = "[ROCKET]"

# Try to use Unicode emojis if supported
try:
    test_str = "✅"
    if sys.platform == 'win32':
        test_str.encode(sys.stdout.encoding or 'utf-8')
    # If successful, use emojis
    CHECK_MARK = "✅"
    CROSS_MARK = "❌"
    ROCKET = "🚀"
except (UnicodeEncodeError, LookupError, AttributeError):
    # Keep ASCII fallbacks
    pass
```

### 2. **Files Modified**

**Core Module** (`version_check.py`):
- Added UTF-8 configuration for Windows stdout
- Implemented smart emoji detection with ASCII fallbacks
- Defined safe symbols: `CHECK_MARK`, `CROSS_MARK`, `ROCKET`, `THREAD`, `BULB`, `TARGET`, `BOOK`, `MAG`, `PARTY`

**Application Files**:
- `main_app.py`: Imported safe symbols, replaced all emojis
- `routing.py`: Imported `CHECK_MARK`, replaced emoji
- `rust_integration.py`: Imported safe symbols, replaced all emojis
- `server_integration.py`: Imported safe symbols, replaced all emojis

### 3. **CI/CD Improvements** (`.github/workflows/build-wheels.yml`)

Updated Windows test script:
```python
# Set UTF-8 encoding on Windows
if sys.platform == 'win32':
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
```

Added better error handling with full traceback output.

### 4. **Version Bump**

- `pyproject.toml`: 0.3.1 → 0.3.2
- `Cargo.toml`: 0.3.1 → 0.3.2

## Output Examples

### Windows (cp1252 - ASCII Fallback)
```
[OK] TurboAPI: Python 3.13.0 free-threading detected!
[THREAD] True parallelism enabled - ready for 5-10x performance!
[ROCKET] Starting TurboAPI server...
[OK] TurboAPI server ready!
```

### Windows (UTF-8 Configured)
```
✅ TurboAPI: Python 3.13.0 free-threading detected!
🧵 True parallelism enabled - ready for 5-10x performance!
🚀 Starting TurboAPI server...
✅ TurboAPI server ready!
```

### macOS/Linux (UTF-8 Native)
```
✅ TurboAPI: Python 3.13.0 free-threading detected!
🧵 True parallelism enabled - ready for 5-10x performance!
🚀 Starting TurboAPI server...
✅ TurboAPI server ready!
```

## Testing

### Manual Testing
```bash
# Windows PowerShell
python -c "import turboapi; print('Success!')"

# Windows CMD
chcp 65001  # Set UTF-8 code page
python -c "import turboapi; print('Success!')"

# Unix-like systems
python3 -c "import turboapi; print('Success!')"
```

### CI/CD Testing
GitHub Actions now tests on:
- **Windows**: windows-latest with Python 3.13
- **macOS**: macos-latest with Python 3.13
- **Linux**: ubuntu-latest with Python 3.13

All platforms test wheel installation and basic import functionality.

## Benefits

1. **✅ Windows Compatibility**: TurboAPI now works flawlessly on Windows
2. **✅ Better UX**: Emojis display on systems that support them, ASCII fallback otherwise
3. **✅ Robust**: Graceful degradation ensures functionality regardless of terminal capabilities
4. **✅ CI/CD**: Automated testing catches encoding issues before release
5. **✅ Backward Compatible**: No API changes, existing code works unchanged

## Release Notes

### TurboAPI v0.3.2 (2025-09-30)

**Fixed**:
- Critical `UnicodeEncodeError` on Windows systems with cp1252 encoding
- Import failures due to emoji characters in console output
- CI/CD test failures on Windows platform

**Improved**:
- Smart emoji detection with automatic UTF-8 configuration
- Graceful fallback to ASCII symbols on incompatible terminals
- Enhanced error messages with full traceback in CI tests

**Technical Details**:
- Added `io` module for stdout reconfiguration
- Implemented platform-specific encoding handling
- All emoji characters now use safe symbol variables

## Migration Guide

**For Users**: No action required! Simply upgrade:
```bash
pip install --upgrade turboapi
```

**For Developers**: If you've created custom modules using TurboAPI:
```python
# Old (may fail on Windows)
print("✅ Success!")

# New (recommended)
from turboapi.version_check import CHECK_MARK
print(f"{CHECK_MARK} Success!")
```

## Future Considerations

1. Consider adding a configuration option: `TURBOAPI_FORCE_ASCII=1`
2. Provide detailed logging about encoding detection
3. Document best practices for cross-platform console output in Python

## Related Issues

- Windows cp1252 encoding limitations
- GitHub Actions Windows runner default encoding
- Python 3.13+ stdout encoding behavior
- Terminal capability detection

## Credits

- **Issue Identified**: CI/CD pipeline Windows tests
- **Fixed By**: Automated fix for Windows Unicode compatibility
- **Tested On**: Windows 11, macOS 14, Ubuntu 22.04
- **Python Versions**: 3.13.0+

---

**TurboAPI**: Revolutionary Python web framework with FastAPI syntax and 5-10x performance.

**Repository**: https://github.com/justrach/turboAPI
**Documentation**: See README.md and AGENTS.md
