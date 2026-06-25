"""
Configure pytest for chaincraft tests.

Relies on ``pip install -e .`` (CI and local dev). No repo-root ``__init__.py`` —
that file broke collection when the checkout directory name is not ``chaincraft``.
"""
