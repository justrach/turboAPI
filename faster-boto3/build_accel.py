"""Build the Zig SigV4 accelerator extension."""

import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path


def build():
    py_include = sysconfig.get_path("include")
    py_libdir = sysconfig.get_config_var("LIBDIR")

    ext_suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
    target_name = f"_sigv4_accel{ext_suffix}"

    zig_dir = Path(__file__).parent / "zig"
    out_dir = Path(__file__).parent / "faster_boto3"

    print("Building SigV4 accelerator...")
    print(f"  Python include: {py_include}")
    print(f"  Python libdir: {py_libdir}")

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

    # Find the built .so/.dylib
    lib_dir = zig_dir / "zig-out" / "lib"
    for f in lib_dir.iterdir():
        if "sigv4_accel" in f.name and (f.suffix == ".so" or f.suffix == ".dylib"):
            dest = out_dir / target_name
            shutil.copy2(f, dest)
            print(f"  Installed: {dest}")
            return

    print("Could not find built library!")
    sys.exit(1)


if __name__ == "__main__":
    build()
