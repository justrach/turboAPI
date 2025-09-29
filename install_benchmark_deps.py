#!/usr/bin/env python3
"""
Install benchmark dependencies for TurboAPI
"""

import subprocess
import sys

def install_dependencies():
    """Install required packages for benchmarking and visualization."""
    packages = [
        "matplotlib>=3.5.0",
        "seaborn>=0.11.0", 
        "pandas>=1.3.0",
        "requests>=2.25.0",
        "httpx>=0.24.0"
    ]
    
    print("📦 Installing benchmark and visualization dependencies...")
    
    for package in packages:
        print(f"Installing {package}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            print(f"✅ {package} installed successfully")
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to install {package}: {e}")
            return False
    
    print("🎉 All dependencies installed successfully!")
    return True

def test_imports():
    """Test that all required packages can be imported."""
    print("\n🧪 Testing imports...")
    
    try:
        import matplotlib.pyplot as plt
        print("✅ matplotlib imported")
        
        import seaborn as sns
        print("✅ seaborn imported")
        
        import pandas as pd
        print("✅ pandas imported")
        
        import requests
        print("✅ requests imported")
        
        import numpy as np
        print("✅ numpy imported")
        
        print("🎯 All visualization libraries are ready!")
        return True
        
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False

if __name__ == "__main__":
    print("🚀 TurboAPI Benchmark Dependencies Installer")
    print("=" * 50)
    
    if install_dependencies():
        if test_imports():
            print("\n✅ Ready to run enhanced benchmarks with visualizations!")
            print("Run: python tests/wrk_benchmark.py")
        else:
            print("\n❌ Some imports failed. Please check the installation.")
    else:
        print("\n❌ Failed to install dependencies.")
