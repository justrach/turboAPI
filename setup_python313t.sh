#!/bin/bash
# Setup Python 3.13 Free-Threading as Default
# Run this script to switch your default Python to 3.13 free-threading

set -e

echo "🐍 Python 3.13 Free-Threading Setup"
echo "===================================="
echo ""

# Check current Python
echo "Current Python versions:"
which -a python python3 python3.13 2>/dev/null || true
echo ""
python3 --version 2>/dev/null || echo "python3 not found"
echo ""

# Check if python3.13t exists
if command -v python3.13t &> /dev/null; then
    echo "✅ python3.13t found at: $(which python3.13t)"
    python3.13t --version
else
    echo "❌ python3.13t not found!"
    echo ""
    echo "📥 You need to install Python 3.13 with free-threading support."
    echo ""
    echo "Option 1 - Download from python.org (EASIEST):"
    echo "   Visit: https://www.python.org/downloads/"
    echo "   Look for: 'Python 3.13.x with experimental free-threading support'"
    echo "   Download and run the macOS installer"
    echo ""
    echo "Option 2 - Build from source (ADVANCED):"
    echo "   cd /tmp"
    echo "   git clone https://github.com/python/cpython.git"
    echo "   cd cpython && git checkout v3.13.4"
    echo "   ./configure --enable-experimental-freethreading --prefix=\$HOME/python313t"
    echo "   make -j\$(sysctl -n hw.ncpu) && make install"
    echo "   # Then add ~/python313t/bin to your PATH"
    echo ""
    echo "After installing, run this script again!"
    exit 1
fi

echo ""
echo "🔧 Setting up shell aliases..."

# Backup zshrc
if [ -f ~/.zshrc ]; then
    cp ~/.zshrc ~/.zshrc.backup.$(date +%Y%m%d_%H%M%S)
    echo "✅ Backed up ~/.zshrc"
fi

# Check if aliases already exist
if grep -q "alias python=\"python3.13t\"" ~/.zshrc 2>/dev/null; then
    echo "⚠️  Aliases already exist in ~/.zshrc"
else
    echo "" >> ~/.zshrc
    echo "# Python 3.13 Free-Threading (added $(date))" >> ~/.zshrc
    echo 'alias python="python3.13t"' >> ~/.zshrc
    echo 'alias python3="python3.13t"' >> ~/.zshrc
    echo 'alias pip="python3.13t -m pip"' >> ~/.zshrc
    echo 'alias pip3="python3.13t -m pip"' >> ~/.zshrc
    echo "✅ Added aliases to ~/.zshrc"
fi

echo ""
echo "🎯 Testing free-threading..."
python3.13t -c "
import sys
has_gil = hasattr(sys, '_current_frames')
print(f'Python Version: {sys.version}')
print(f'Has GIL: {has_gil}')
print(f'Free-threading: {not has_gil}')

if not has_gil:
    print('✅ FREE-THREADING IS ENABLED!')
else:
    print('❌ WARNING: GIL is still present - this may not be a free-threading build')
"

echo ""
echo "✨ Setup complete!"
echo ""
echo "⚠️  IMPORTANT: Run this command to activate the changes:"
echo "   source ~/.zshrc"
echo ""
echo "Then test with:"
echo "   python --version"
echo "   python -c \"import sys; print('Free-threading:', not hasattr(sys, '_current_frames'))\""
echo ""
echo "🚀 To use TurboAPI with free-threading:"
echo "   cd /Users/rachpradhan/rusty/turboAPI"
echo "   python3.13t -m venv .venv-freethreading"
echo "   source .venv-freethreading/bin/activate"
echo "   pip install -e python/"
echo "   maturin develop --manifest-path Cargo.toml"
echo ""
