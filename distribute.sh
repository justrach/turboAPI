#!/bin/bash
# distribute.sh - Script to build and upload Tatsat to PyPI
# Usage: ./distribute.sh [test]
# Add 'test' argument to upload to TestPyPI instead of PyPI

set -e  # Exit immediately if a command exits with a non-zero status

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if we're uploading to test.pypi.org or pypi.org
if [ "$1" == "test" ]; then
    PYPI_REPO="--repository-url https://test.pypi.org/legacy/"
    PYPI_NAME="TestPyPI"
else
    PYPI_REPO=""
    PYPI_NAME="PyPI"
fi

echo -e "${YELLOW}=== Tatsat Distribution Script ===${NC}"
echo -e "${YELLOW}This script will build and upload Tatsat to $PYPI_NAME${NC}"

# Ensure the script can execute from any directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check if required tools are installed
echo -e "\n${YELLOW}Checking required tools...${NC}"
command -v python3 >/dev/null 2>&1 || { echo -e "${RED}Python 3 is required but not installed.${NC}" >&2; exit 1; }
command -v pip3 >/dev/null 2>&1 || { echo -e "${RED}pip3 is required but not installed.${NC}" >&2; exit 1; }
command -v twine >/dev/null 2>&1 || { 
    echo -e "${YELLOW}twine not found. Installing...${NC}"
    pip3 install twine
}
command -v build >/dev/null 2>&1 || { 
    echo -e "${YELLOW}build package not found. Installing...${NC}"
    pip3 install build
}

# Clean previous builds
echo -e "\n${YELLOW}Cleaning previous builds...${NC}"
rm -rf build/ dist/ *.egg-info/

# Update version if needed
echo -e "\n${YELLOW}Current version in setup.py:${NC}"
grep -n "version=" setup.py
echo ""
read -p "Do you want to update the version? (y/n): " update_version
if [[ $update_version == "y" || $update_version == "Y" ]]; then
    read -p "Enter new version (e.g., 0.1.1): " new_version
    sed -i.bak "s/version=\"[0-9]*\.[0-9]*\.[0-9]*\"/version=\"$new_version\"/" setup.py
    rm setup.py.bak
    echo -e "${GREEN}Version updated to $new_version${NC}"
fi

# Create README.md for PyPI if not exists
if [ ! -f README.md ]; then
    echo -e "\n${YELLOW}README.md not found. Creating a simple one for PyPI...${NC}"
    cat > README.md << EOF
# Tatsat

A high-performance web framework with elegant syntax and powerful validation using Satya.

## Features

- Starlette-compatible API with enhanced features
- Built-in validation using Satya models
- Fast performance with minimal overhead
- Simple and intuitive interface

## Installation

```bash
pip install tatsat
```

## Quick Start

```python
from tatsat import Tatsat
from satya import Model, Field

app = Tatsat()

class Item(Model):
    name: str = Field()
    price: float = Field(gt=0)

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.post("/items/")
def create_item(item: Item):
    return item

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

## Documentation

For more information, visit the [documentation](https://github.com/yourusername/tatsat).
EOF
    echo -e "${GREEN}Created README.md${NC}"
fi

# Check long description (README.md) rendering
echo -e "\n${YELLOW}Checking README.md rendering for PyPI...${NC}"
python3 -m pip install --upgrade readme-renderer
python3 -m readme_renderer README.md >/dev/null 2>&1 || {
    echo -e "${RED}Warning: README.md might not render correctly on PyPI.${NC}"
    read -p "Continue anyway? (y/n): " continue_anyway
    if [[ $continue_anyway != "y" && $continue_anyway != "Y" ]]; then
        exit 1
    fi
}

# Build the distribution
echo -e "\n${YELLOW}Building distribution...${NC}"
python3 -m build

# Verify the built distribution
echo -e "\n${YELLOW}Verifying the built distribution...${NC}"
python3 -m twine check dist/*

# Confirm upload
echo -e "\n${YELLOW}Ready to upload to $PYPI_NAME.${NC}"
read -p "Do you want to continue with the upload? (y/n): " do_upload

if [[ $do_upload == "y" || $do_upload == "Y" ]]; then
    # Upload to PyPI
    echo -e "\n${YELLOW}Uploading to $PYPI_NAME...${NC}"
    if [ -z "$PYPI_REPO" ]; then
        python3 -m twine upload dist/*
    else
        python3 -m twine upload $PYPI_REPO dist/*
    fi
    echo -e "\n${GREEN}Upload complete!${NC}"
    
    if [ "$PYPI_NAME" == "TestPyPI" ]; then
        echo -e "\n${YELLOW}To install from TestPyPI:${NC}"
        echo "pip install --index-url https://test.pypi.org/simple/ tatsat"
    else
        echo -e "\n${YELLOW}To install from PyPI:${NC}"
        echo "pip install tatsat"
    fi
else
    echo -e "\n${YELLOW}Upload canceled.${NC}"
fi

echo -e "\n${GREEN}Done!${NC}"
