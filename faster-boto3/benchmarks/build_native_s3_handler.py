"""Build the TurboAPI native S3 benchmark handler library."""

from __future__ import annotations

import subprocess
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    source = root / "native_s3_handler.zig"
    out = root / "libnative_s3_handler.dylib"

    subprocess.run(
        [
            "zig",
            "build-lib",
            "-dynamic",
            "-OReleaseFast",
            f"-Mroot={source}",
            "-femit-bin=" + str(out),
        ],
        check=True,
    )
    subprocess.run(
        ["codesign", "--force", "--sign", "-", str(out)],
        check=True,
        capture_output=True,
        text=True,
    )
    print(out)


if __name__ == "__main__":
    main()
