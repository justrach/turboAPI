"""
Setup script for TurboAPI Python package.
"""

from setuptools import setup, find_packages

setup(
    name="turboapi",
    version="0.1.0",
    description="A high-performance Python web framework for the no-GIL era",
    long_description=open("../README.md").read(),
    long_description_content_type="text/markdown",
    author="TurboAPI Team",
    author_email="team@turboapi.dev",
    url="https://github.com/turboapi/turboapi",
    packages=find_packages(),
    python_requires=">=3.12",  # Will be 3.14+ when no-GIL is stable
    install_requires=[
        # The Rust extension will be built separately
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
        ]
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.14",
        "Programming Language :: Rust",
        "Topic :: Internet :: WWW/HTTP :: HTTP Servers",
        "Topic :: Software Development :: Libraries :: Application Frameworks",
    ],
    keywords="web framework http server rust performance no-gil",
)
