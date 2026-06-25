"""
Configure pytest for chaincraft tests.

Relies on ``pip install -e .`` (CI and local dev). No repo-root ``__init__.py`` —
that file broke collection when the checkout directory name is not ``chaincraft``.
"""

import glob
import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def cleanup_node_db_artifacts():
    """Remove ndbm files left in the repo root after the test session."""
    yield
    for pattern in ("node_*.db*", "__test__.db*"):
        for path in glob.glob(pattern):
            try:
                os.remove(path)
            except OSError:
                pass
