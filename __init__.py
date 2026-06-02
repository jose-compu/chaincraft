"""
Chaincraft - A platform for blockchain education and prototyping.

This package provides the fundamental components needed to create distributed networks,
implement consensus mechanisms, and prototype blockchain applications.
"""

__version__ = "0.6.0"
__author__ = "Chaincraft Contributors"
__email__ = "chaincraft@example.com"

from .chaincraft import (
    ChaincraftNode,
    SharedObject,
    SharedObjectException,
    SharedMessage,
    IndexHelper,
)

__all__ = [
    "ChaincraftNode",
    "SharedObject",
    "SharedObjectException",
    "SharedMessage",
    "IndexHelper",
    "__version__",
]
