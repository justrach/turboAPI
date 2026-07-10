"""Setuptools compatibility shim for the prebuilt Zig extension."""

from pathlib import Path

from setuptools import Distribution, setup


class BinaryDistribution(Distribution):
    """Mark a wheel as binary only after the Zig extension has been built."""

    def has_ext_modules(self) -> bool:
        package_dir = Path(__file__).parent / "python" / "turboapi"
        return any(package_dir.glob("turbonet*.so")) or any(package_dir.glob("turbonet*.pyd"))


setup(distclass=BinaryDistribution)
