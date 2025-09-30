# Python 3.13 Free-Threading Setup Guide

## Current Status
- ✅ You have Python 3.13.4 installed at `/opt/homebrew/bin/python3.13`
- ❌ You don't have the free-threading build (`python3.13t`)

## Step 1: Install Python 3.13 Free-Threading Build

### Option A: Using python.org Installer (Recommended)
```bash
# Download from python.org
# Go to: https://www.python.org/downloads/
# Look for "Python 3.13.x installer with free-threading experimental support"
# Install it - it will create python3.13t
```

### Option B: Build from Source (Advanced)
```bash
# Clone Python source
git clone https://github.com/python/cpython.git
cd cpython
git checkout v3.13.4

# Configure with free-threading enabled
./configure --enable-experimental-freethreading --prefix=$HOME/python313t
make -j$(sysctl -n hw.ncpu)
make install

# This will create ~/python313t/bin/python3.13t
```

### Option C: Using pyenv (If available)
```bash
# Install pyenv if not already installed
brew install pyenv

# Install Python 3.13t (free-threading)
PYTHON_CONFIGURE_OPTS="--enable-experimental-freethreading" pyenv install 3.13.4

# Set as global default
pyenv global 3.13.4
```

## Step 2: Verify Free-Threading Installation

```bash
# Check if python3.13t exists
which python3.13t

# Verify free-threading is enabled
python3.13t -c "import sys; print('Free-threading:', not hasattr(sys, '_current_frames'))"
# Should print: Free-threading: True
```

## Step 3: Set as Default Python

### Method 1: Shell Aliases (Recommended for testing)
Add to your `~/.zshrc`:
```bash
# Python 3.13 free-threading as default
alias python='python3.13t'
alias python3='python3.13t'
alias pip='python3.13t -m pip'
alias pip3='python3.13t -m pip'
```

Then reload:
```bash
source ~/.zshrc
```

### Method 2: Homebrew Link (System-wide)
```bash
# Unlink current python3
brew unlink python@3.13

# If you installed via homebrew, link the free-threading version
# (This requires homebrew to have a free-threading formula)
```

### Method 3: PATH Priority
Add to your `~/.zshrc`:
```bash
# Add python3.13t directory to PATH first
export PATH="/path/to/python313t/bin:$PATH"
```

## Step 4: Create Virtual Environment with Free-Threading

```bash
# Create a free-threading venv
python3.13t -m venv turbo-freethreaded

# Activate it
source turbo-freethreaded/bin/activate

# Verify
python --version  # Should show Python 3.13.x
python -c "import sys; print('Free-threading:', not hasattr(sys, '_current_frames'))"
```

## Step 5: Install TurboAPI in Free-Threading Environment

```bash
cd /Users/rachpradhan/rusty/turboAPI

# Install Python package
pip install -e python/

# Build Rust core
maturin develop --manifest-path Cargo.toml

# Test
python -c "from turboapi import TurboAPI, get_python_threading_info; info = get_python_threading_info(); print(info)"
```

## Quick Commands to Run Now

```bash
# 1. Check what you currently have
which python python3 python3.13 python3.13t
python3 --version
python3.13 --version

# 2. If python3.13t doesn't exist, you need to install it (see options above)

# 3. Once you have python3.13t, set up aliases
echo 'alias python="python3.13t"' >> ~/.zshrc
echo 'alias python3="python3.13t"' >> ~/.zshrc
echo 'alias pip="python3.13t -m pip"' >> ~/.zshrc
source ~/.zshrc

# 4. Verify
python --version
python -c "import sys; print('Free-threading:', not hasattr(sys, '_current_frames'))"
```

## Troubleshooting

### Python 3.13t Not Found
- **Solution**: You need to install the free-threading build. The standard Python 3.13 from Homebrew does NOT include free-threading.
- Download from: https://www.python.org/downloads/ (look for experimental free-threading builds)
- Or build from source with `--enable-experimental-freethreading`

### Import Errors After Switching
- **Solution**: Reinstall all packages in the new Python environment
```bash
pip install -e python/
maturin develop --manifest-path Cargo.toml
```

### Performance Not Improved
- **Solution**: Verify you're actually using free-threading:
```bash
python -c "from turboapi import get_python_threading_info; import json; print(json.dumps(get_python_threading_info(), indent=2))"
```

## Expected Output When Correctly Set Up

```python
{
  "python_version": "3.13.4",
  "free_threading": true,
  "implementation": "cpython",
  "performance": "Excellent - True parallelism",
  "concurrency": "Native threads (no GIL)",
  "gil_overhead": "None (no GIL)"
}
```

## References
- [PEP 703 – Making the Global Interpreter Lock Optional](https://peps.python.org/pep-0703/)
- [Python 3.13 Release Notes](https://docs.python.org/3.13/whatsnew/3.13.html)
- [Free-Threading Build Instructions](https://docs.python.org/3.13/using/configure.html#cmdoption-enable-experimental-freethreading)
