"""Build the Zig Redis accelerator extension."""
import shutil, subprocess, sys, sysconfig
from pathlib import Path

def build():
    py_include = sysconfig.get_path("include")
    py_libdir = sysconfig.get_config_var("LIBDIR")
    ext_suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".so"

    zig_dir = Path(__file__).parent / "zig"
    out_dir = Path(__file__).parent / "faster_redis"

    print(f"Building Redis accelerator (Python: {py_include})")
    result = subprocess.run([
        "zig", "build",
        f"-Dpy-include={py_include}",
        f"-Dpy-libdir={py_libdir}",
        "-Doptimize=ReleaseFast",
    ], cwd=zig_dir)
    if result.returncode != 0:
        print("Build failed!"); sys.exit(1)

    lib_dir = zig_dir / "zig-out" / "lib"
    for f in lib_dir.iterdir():
        if "redis_accel" in f.name and (f.suffix == ".so" or f.suffix == ".dylib"):
            dest = out_dir / f"_redis_accel{ext_suffix}"
            shutil.copy2(f, dest)
            print(f"Installed: {dest}")
            return
    print("Could not find built library!"); sys.exit(1)

if __name__ == "__main__":
    build()
