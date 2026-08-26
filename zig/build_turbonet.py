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
import platform
import re
import shutil
import subprocess
import sys
import sysconfig

REQUIRED_ZIG_VERSION = "0.17.0-dev.1862+40ebd8162"
_MACOS_DEPLOYMENT_TARGET = re.compile(r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?$")


def macos_zig_target(machine: str, deployment_target: str) -> str:
    """Return a Zig target with an explicit macOS deployment floor."""
    architectures = {
        "arm64": "aarch64",
        "aarch64": "aarch64",
        "x86_64": "x86_64",
        "amd64": "x86_64",
    }
    architecture = architectures.get(machine.strip().lower())
    if architecture is None:
        raise ValueError(f"unsupported macOS architecture: {machine}")
    if not _MACOS_DEPLOYMENT_TARGET.fullmatch(deployment_target):
        raise ValueError(f"invalid macOS deployment target: {deployment_target}")
    return f"{architecture}-macos.{deployment_target}"


def require_zig_version():
    zig = shutil.which("zig")
    if zig is None:
        raise SystemExit(f"Zig {REQUIRED_ZIG_VERSION} is required but zig is not on PATH")

    result = subprocess.run([zig, "version"], check=True, capture_output=True, text=True)
    actual = result.stdout.strip()
    if actual != REQUIRED_ZIG_VERSION:
        raise SystemExit(f"Zig {REQUIRED_ZIG_VERSION} is required; found {actual} at {zig}")


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
    parser.add_argument(
        "--target",
        help="Explicit Zig target, including a minimum OS or libc version",
    )
    parser.add_argument(
        "--macos-deployment-target",
        help="Build a native macOS extension with this explicit deployment floor",
    )
    parser.add_argument(
        "--glibc-compat",
        action="store_true",
        help="Include compatibility code for the manylinux glibc floor",
    )
    args = parser.parse_args()

    if args.target and args.macos_deployment_target:
        parser.error("--target and --macos-deployment-target are mutually exclusive")
    if args.macos_deployment_target and platform.system() != "Darwin":
        parser.error("--macos-deployment-target requires a macOS build host")

    require_zig_version()
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

    cmd = [
        "zig",
        "build",
        f"-Dpython={py_arg}",
        f"-Dpy-include={info['include']}",
        f"-Dpy-libdir={info['libdir']}",
    ]

    build_target = args.target
    if args.macos_deployment_target:
        try:
            build_target = macos_zig_target(platform.machine(), args.macos_deployment_target)
        except ValueError as error:
            parser.error(str(error))
    if build_target:
        cmd.append(f"-Dtarget={build_target}")

    if args.glibc_compat:
        cmd.append("-Dglibc-compat=true")

    if args.release:
        cmd.append("-Doptimize=ReleaseFast")

    print(f"\n⚡ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=zig_dir)
    if result.returncode != 0:
        sys.exit(result.returncode)

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
        print("   🧵 Free-threaded build — GIL disabled!")


if __name__ == "__main__":
    main()
