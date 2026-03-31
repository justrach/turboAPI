"""
Setup script for TurboAPI Python package.
"""

from setuptools import find_packages, setup

setup(
    name="turboapi",
    version="1.0.25",
    description="A high-performance Python web framework for the no-GIL era",
    long_description=open("../README.md").read(),
    long_description_content_type="text/markdown",
    author="TurboAPI Team",
    author_email="team@turboapi.dev",
    url="https://github.com/turboapi/turboapi",
    packages=find_packages(),
    python_requires=">=3.14",
    install_requires=[
        # The Zig extension is built separately via zig/build_turbonet.py
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "black>=23.0.0",
            "isort>=5.12.0",
            "mypy>=1.0.0",
        ],
        "benchmark": [
            "httpx>=0.24.0",
            "uvloop>=0.17.0",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.14",
        "Programming Language :: Other :: Zig",
        "Topic :: Internet :: WWW/HTTP :: HTTP Servers",
        "Topic :: Software Development :: Libraries :: Application Frameworks",
    ],
    keywords="web framework http server zig performance no-gil free-threading",
)
