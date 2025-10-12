#!/usr/bin/env python3
"""
Test Package Integrity - Validates Rust module bundling before release

This script ensures that:
1. The Rust core (turbonet) is properly bundled
2. All imports work correctly
3. Basic functionality is operational

Run this before committing/releasing to catch bundling issues early!
"""

import sys
import subprocess
import tempfile
import shutil
from pathlib import Path


def print_status(message, status="info"):
    """Print colored status messages"""
    colors = {
        "info": "\033[94m",      # Blue
        "success": "\033[92m",   # Green
        "warning": "\033[93m",   # Yellow
        "error": "\033[91m",     # Red
        "reset": "\033[0m"
    }
    
    symbols = {
        "info": "ℹ️",
        "success": "✅",
        "warning": "⚠️",
        "error": "❌"
    }
    
    color = colors.get(status, colors["info"])
    symbol = symbols.get(status, "")
    reset = colors["reset"]
    
    print(f"{color}{symbol} {message}{reset}")


def run_command(cmd, cwd=None, capture_output=True):
    """Run a shell command and return the result"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=capture_output,
            text=True,
            check=True
        )
        return result.stdout if capture_output else None
    except subprocess.CalledProcessError as e:
        print_status(f"Command failed: {cmd}", "error")
        if capture_output:
            print(f"STDOUT: {e.stdout}")
            print(f"STDERR: {e.stderr}")
        return None


def test_local_development_install():
    """Test 1: Verify local development install works"""
    print_status("Test 1: Testing local development install...", "info")
    
    # Build and install in development mode
    result = run_command("cd python && maturin develop --release")
    
    if result is None:
        print_status("Failed to build with maturin", "error")
        return False
    
    print_status("Local development build successful", "success")
    return True


def test_rust_module_import():
    """Test 2: Verify Rust module can be imported"""
    print_status("Test 2: Testing Rust module import...", "info")
    
    test_code = """
import sys
try:
    from turboapi import turbonet
    print("SUCCESS: turbonet imported")
    print(f"Available: {hasattr(turbonet, 'TurboServer')}")
    sys.exit(0)
except ImportError as e:
    print(f"FAILED: {e}")
    sys.exit(1)
"""
    
    result = subprocess.run(
        [sys.executable, "-c", test_code],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print_status("Failed to import turbonet module", "error")
        print(result.stdout)
        print(result.stderr)
        return False
    
    if "SUCCESS" in result.stdout and "True" in result.stdout:
        print_status("Rust module imported successfully", "success")
        return True
    else:
        print_status("Rust module import incomplete", "error")
        print(result.stdout)
        return False


def test_turboapi_basic_functionality():
    """Test 3: Verify basic TurboAPI functionality"""
    print_status("Test 3: Testing basic TurboAPI functionality...", "info")
    
    test_code = """
import sys
try:
    from turboapi import TurboAPI
    
    # Create app
    app = TurboAPI(title="Test App")
    
    # Add a simple route
    @app.get("/test")
    def test_route():
        return {"status": "ok"}
    
    # Check that route was registered
    if hasattr(app, 'routes') and len(app.routes) > 0:
        print("SUCCESS: Route registered")
        sys.exit(0)
    else:
        print("FAILED: Route not registered")
        sys.exit(1)
        
except Exception as e:
    print(f"FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
"""
    
    result = subprocess.run(
        [sys.executable, "-c", test_code],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print_status("Basic functionality test failed", "error")
        print(result.stdout)
        print(result.stderr)
        return False
    
    if "SUCCESS" in result.stdout:
        print_status("Basic functionality works", "success")
        return True
    else:
        print_status("Basic functionality incomplete", "error")
        return False


def test_wheel_build():
    """Test 4: Verify wheel can be built"""
    print_status("Test 4: Testing wheel build...", "info")
    
    # Create temporary directory for wheel
    with tempfile.TemporaryDirectory() as tmpdir:
        print_status(f"Building wheel in {tmpdir}...", "info")
        
        result = run_command(
            f"cd python && maturin build --release --out {tmpdir}",
            capture_output=True
        )
        
        if result is None:
            print_status("Failed to build wheel", "error")
            return False
        
        # Check if wheel was created
        wheels = list(Path(tmpdir).glob("*.whl"))
        
        if not wheels:
            print_status("No wheel file found", "error")
            return False
        
        wheel_path = wheels[0]
        print_status(f"Wheel built successfully: {wheel_path.name}", "success")
        
        # Inspect wheel contents
        print_status("Inspecting wheel contents...", "info")
        result = run_command(f"unzip -l {wheel_path}", capture_output=True)
        
        if result and "turbonet" in result:
            print_status("Rust module found in wheel ✓", "success")
            
            # Show relevant files
            lines = [line for line in result.split('\n') if 'turbonet' in line or 'turboapi' in line]
            for line in lines[:10]:  # Show first 10 relevant files
                print(f"  {line.strip()}")
            
            return True
        else:
            print_status("Rust module NOT found in wheel ✗", "error")
            print("Wheel contents:")
            print(result)
            return False


def test_wheel_install_in_venv():
    """Test 5: Verify wheel installs correctly in fresh venv"""
    print_status("Test 5: Testing wheel install in fresh venv...", "info")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        venv_dir = Path(tmpdir) / "test_venv"
        wheel_dir = Path(tmpdir) / "wheels"
        wheel_dir.mkdir()
        
        # Build wheel
        print_status("Building wheel...", "info")
        result = run_command(
            f"cd python && maturin build --release --out {wheel_dir}",
            capture_output=True
        )
        
        if result is None:
            print_status("Failed to build wheel", "error")
            return False
        
        wheels = list(wheel_dir.glob("*.whl"))
        if not wheels:
            print_status("No wheel found", "error")
            return False
        
        wheel_path = wheels[0]
        
        # Create venv
        print_status("Creating test virtual environment...", "info")
        result = run_command(f"{sys.executable} -m venv {venv_dir}")
        
        if result is None:
            print_status("Failed to create venv", "error")
            return False
        
        # Install wheel in venv
        pip_path = venv_dir / "bin" / "pip"
        python_path = venv_dir / "bin" / "python"
        
        print_status(f"Installing wheel: {wheel_path.name}", "info")
        result = run_command(f"{pip_path} install {wheel_path}")
        
        if result is None:
            print_status("Failed to install wheel", "error")
            return False
        
        # Test import in venv
        print_status("Testing import in venv...", "info")
        test_code = """
try:
    from turboapi import turbonet
    from turboapi import TurboAPI
    app = TurboAPI()
    print("SUCCESS")
except Exception as e:
    print(f"FAILED: {e}")
    import traceback
    traceback.print_exc()
"""
        
        result = run_command(
            f"{python_path} -c '{test_code}'",
            capture_output=True
        )
        
        if result and "SUCCESS" in result:
            print_status("Wheel installs and imports correctly ✓", "success")
            return True
        else:
            print_status("Wheel install/import failed ✗", "error")
            print(result)
            return False


def main():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("🧪 TurboAPI Package Integrity Test Suite")
    print("=" * 70 + "\n")
    
    tests = [
        ("Local Development Install", test_local_development_install),
        ("Rust Module Import", test_rust_module_import),
        ("Basic Functionality", test_turboapi_basic_functionality),
        ("Wheel Build", test_wheel_build),
        ("Wheel Install in Venv", test_wheel_install_in_venv),
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        print(f"\n{'─' * 70}")
        try:
            results[test_name] = test_func()
        except Exception as e:
            print_status(f"Test crashed: {e}", "error")
            import traceback
            traceback.print_exc()
            results[test_name] = False
    
    # Summary
    print(f"\n{'=' * 70}")
    print("📊 Test Summary")
    print("=" * 70 + "\n")
    
    for test_name, passed in results.items():
        status = "success" if passed else "error"
        print_status(f"{test_name}: {'PASSED' if passed else 'FAILED'}", status)
    
    total = len(results)
    passed = sum(results.values())
    
    print(f"\n{'=' * 70}")
    if passed == total:
        print_status(f"All {total} tests passed! ✨", "success")
        print_status("Package is ready for release! 🚀", "success")
        return 0
    else:
        print_status(f"{passed}/{total} tests passed", "warning")
        print_status("Fix issues before releasing!", "error")
        return 1


if __name__ == "__main__":
    sys.exit(main())
