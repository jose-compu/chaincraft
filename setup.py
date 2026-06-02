#!/usr/bin/env python
"""
Chaincraft setup script for backward compatibility.
Modern installation should use pyproject.toml directly.
"""

from setuptools import setup

# This setup.py file is just a compatibility layer
# For backward compatibility with older pip/setuptools versions
setup(
    name="chaincraft",
    version="0.6.0",
    packages=["chaincraft", "examples"],
    package_data={"": ["*.md", "*.txt"]},
    include_package_data=True,
)
