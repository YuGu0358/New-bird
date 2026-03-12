#!/usr/bin/env python3

from setuptools import find_packages, setup

with open("cli_anything/trading_platform/README.md", "r", encoding="utf-8") as handle:
    long_description = handle.read()

setup(
    name="cli-anything-trading-platform",
    version="1.0.0",
    author="cli-anything contributors",
    description="CLI harness for the personal trading platform",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/HKUDS/CLI-Anything",
    packages=find_packages(include=["cli_anything", "cli_anything.*"]),
    python_requires=">=3.10",
    install_requires=[
        "click>=8.0.0",
        "httpx>=0.28.0",
        "prompt-toolkit>=3.0.0",
    ],
    entry_points={
        "console_scripts": [
            "cli-anything-trading-platform=cli_anything.trading_platform.trading_platform_cli:main",
        ],
    },
    include_package_data=True,
    zip_safe=False,
)
