"""Build the Zig accelerator extensions (SigV4 + HTTP)."""

import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path


LIBS = {
    "sigv4_accel": "_sigv4_accel",
    "http_accel": "_http_accel",
    "parser_accel": "_parser_accel",
}


def build():
    py_include = sysconfig.get_path("include")
    py_libdir = sysconfig.get_config_var("LIBDIR")
    ext_suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".so"

    zig_dir = Path(__file__).parent / "zig"
    out_dir = Path(__file__).parent / "faster_boto3"

    print("Building Zig accelerators...")
    print(f"  Python include: {py_include}")
    print(f"  Python libdir:  {py_libdir}")

    cmd = [
        "zig", "build",
        f"-Dpy-include={py_include}",
        f"-Dpy-libdir={py_libdir}",
        "-Doptimize=ReleaseFast",
    ]

    result = subprocess.run(cmd, cwd=zig_dir)
    if result.returncode != 0:
        print("Build failed!")
        sys.exit(1)

    lib_dir = zig_dir / "zig-out" / "lib"
    installed = 0
    for f in lib_dir.iterdir():
        for zig_name, py_name in LIBS.items():
            if zig_name in f.name and (f.suffix == ".so" or f.suffix == ".dylib"):
                dest = out_dir / f"{py_name}{ext_suffix}"
                shutil.copy2(f, dest)
                print(f"  Installed: {dest}")
                installed += 1

    if installed < len(LIBS):
        print(f"Warning: only {installed}/{len(LIBS)} libraries built")
    else:
        print(f"  All {installed} accelerators built successfully")


if __name__ == "__main__":
    build()
