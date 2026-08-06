# Contributing to Chaincraft

Thank you for your interest in contributing to Chaincraft! This document provides guidelines and instructions for setting up your local environment, running tests, and submitting changes.

## Development Setup

To work on Chaincraft, clone the repository and install the package in editable mode with development dependencies:

```bash
git clone [https://github.com/jose-compu/chaincraft.git](https://github.com/jose-compu/chaincraft.git)
cd chaincraft
pip install -e ".[dev]"
```

## Running Unit Tests

We use `pytest` for unit testing. Before submitting a pull request, verify that all unit tests pass:

```bash
pytest
```

## Repository Structure & Examples

- **Code & Core**: Located in the package source folders.
- **Unit Tests**: Located in the `tests/` directory.
- **Examples**: Usage scripts and demo code live in the `examples/` directory.

## Pull Request Guidelines

When opening a Pull Request (PR):
1. **Tests**: Ensure any new code includes unit tests and all existing tests pass.
2. **Changelog**: If your change is user-facing, add a summary note under `CHANGELOG.md`.
3. **Link Issue**: Mention the issue number in your PR description (e.g., `Closes #111`).
