"""
Setup file for TurboAPI package.
"""

from setuptools import setup, find_packages

setup(
    name="turboapi",
    version="0.1.0",
    description="A high-performance web framework with elegant syntax and powerful validation using satya",
    author="TurboAPI Team",
    author_email="info@turboapi.com",
    packages=find_packages(),
    install_requires=[
        "starlette>=0.28.0",
        "uvicorn>=0.23.0",
        "satya>=0.2.5",  # Added Satya as a required dependency
    ],
    extras_require={
        "test": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.20.0",
            "httpx>=0.24.0",
        ],
        "dev": [
            "black>=23.0.0",
            "isort>=5.12.0",
            "flake8>=6.0.0",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Framework :: TurboAPI",
    ],
    python_requires=">=3.8",
)
