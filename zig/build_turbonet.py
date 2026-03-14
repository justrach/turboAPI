#!/usr/bin/env python3
"""
Auto-detect the running Python and build the Zig turbonet extension for it.

Usage:
    python3.14t zig/build_turbonet.py          # builds for 3.14t free-threaded
    python3.13  zig/build_turbonet.py          # builds for 3.13
    python3.14  zig/build_turbonet.py          # builds for 3.14
    python      zig/build_turbonet.py --install # build + copy into package dir
"""

import argparse
import importlib.machinery
import os
import shutil
import subprocess
import sys
import sysconfig


def detect_python():
    ver = sys.version_info
    free_threaded = hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled()
    include = sysconfig.get_path("include")
    libdir = sysconfig.get_config_var("LIBDIR")
    suffix = importlib.machinery.EXTENSION_SUFFIXES[0]  # e.g. .cpython-314t-darwin.so

    if free_threaded:
        label = f"{ver.major}.{ver.minor}t"
    else:
        label = f"{ver.major}.{ver.minor}"

    return {
        "version": f"{ver.major}.{ver.minor}.{ver.micro}",
        "label": label,
        "free_threaded": free_threaded,
        "include": include,
        "libdir": libdir,
        "suffix": suffix,
        "gil": "DISABLED" if free_threaded else "enabled",
    }


def main():
    parser = argparse.ArgumentParser(description="Build turbonet for the running Python")
    parser.add_argument("--install", action="store_true", help="Copy .so into python/turboapi/")
    parser.add_argument("--release", action="store_true", help="Build with ReleaseFast")
    args = parser.parse_args()

    info = detect_python()
    zig_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(zig_dir)

    print(f"🐍 Python {info['version']} (GIL: {info['gil']})")
    print(f"📦 Extension suffix: {info['suffix']}")
    print(f"📁 Include: {info['include']}")
    print(f"📁 Lib: {info['libdir']}")

    # Map to build.zig -Dpython= value
    if info["free_threaded"]:
        py_arg = "3.14t"
    elif info["label"].startswith("3.14"):
        py_arg = "3.14"
    else:
        py_arg = "3.13"

    cmd = ["zig", "build", f"-Dpython={py_arg}",
           f"-Dpy-include={info['include']}",
           f"-Dpy-libdir={info['libdir']}"]

    # Resolve dhi path: env var > sibling directory > error
    dhi_path = os.environ.get("DHI_PATH")
    if not dhi_path:
        # Check common sibling locations
        for candidate in [
            os.path.join(os.path.dirname(project_dir), "dhi"),
            os.path.join(project_dir, "dhi"),
            os.path.expanduser("~/dhi"),
        ]:
            if os.path.isdir(candidate):
                dhi_path = candidate
                break
    if not dhi_path:
        print("❌ dhi repository not found. Set DHI_PATH or clone it as a sibling:")
        print("   git clone https://github.com/justrach/dhi.git ../dhi")
        sys.exit(1)
    cmd.append(f"-Ddhi-path={dhi_path}")
    print(f"📦 dhi: {dhi_path}")

    if args.release:
        cmd.append("-Doptimize=ReleaseFast")

    print(f"\n⚡ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=zig_dir)
    if result.returncode != 0:
        sys.exit(result.returncode)

    import platform
    lib_ext = ".dylib" if platform.system() == "Darwin" else ".so"
    dylib = os.path.join(zig_dir, "zig-out", "lib", f"libturbonet{lib_ext}")
    target = os.path.join(project_dir, "python", "turboapi", f"turbonet{info['suffix']}")

    if args.install:
        shutil.copy2(dylib, target)
        print(f"\n✅ Installed: {target}")
    else:
        print(f"\n✅ Built: {dylib}")
        print(f"   To install: cp {dylib} {target}")

    print(f"   Python: {sys.executable}")
    if info["free_threaded"]:
        print(f"   🧵 Free-threaded build — GIL disabled!")


if __name__ == "__main__":
    main()
