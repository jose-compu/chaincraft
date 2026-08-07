# Publishing Chaincraft to PyPI

This document explains how to set up automatic publishing of the Chaincraft Python package to PyPI using GitHub Actions.

## Prerequisites

1. **PyPI Account**: You need a PyPI account at https://pypi.org/
2. **GitHub Repository**: The code should be in a GitHub repository
3. **Trusted Publishing**: Set up trusted publishing between GitHub and PyPI (recommended)

## Setting up Trusted Publishing (Recommended)

Trusted publishing is the modern, secure way to publish packages to PyPI without using API tokens.

### 1. Configure PyPI

1. Go to https://pypi.org/manage/account/publishing/
2. Click "Add a new pending publisher"
3. Fill in the details:
   - **PyPI project name**: `chaincraft`
   - **Owner**: `jio-gl` (your GitHub username/organization)
   - **Repository name**: `chaincraft`
   - **Workflow name**: `publish-to-pypi.yml`
   - **Environment name**: `release`

### 2. Create GitHub Environment

1. Go to your GitHub repository settings
2. Navigate to "Environments"
3. Create a new environment named `release`
4. Optionally, add protection rules (e.g., require manual approval)

## How the Workflow Works

The GitHub workflow (`.github/workflows/publish-to-pypi.yml`) is triggered when you create a new release:

1. **Test Phase**: Runs tests across multiple Python versions (3.9-3.12)
2. **Build Phase**: Builds the package (both source distribution and wheel)
3. **Publish Phase**: Publishes to PyPI using trusted publishing

## Creating a Release

To publish a new version:

1. **Update Version**: Set the same version in `pyproject.toml`, `setup.py`, and `chaincraft/__init__.py` (and `examples/__init__.py` if present).
2. **Changelog**: Document the release in `CHANGELOG.md` (0.7.0 = BIP-340 Schnorr only).
3. **Commit & merge**: Land the release PR on `main`.
4. **Tag & release**:
   - Tag `vX.Y.Z` on `main` and push the tag (triggers PyPI workflow on `v*` tags).
   - Or: GitHub → Releases → “Create a new release” with tag `vX.Y.Z` and notes from `CHANGELOG.md`.

Example for 0.7.0 after merge to `main`:

```bash
git checkout main && git pull
git tag -a v0.7.0 -m "Chaincraft v0.7.0 — BIP-340 Schnorr"
git push origin v0.7.0
gh release create v0.7.0 --title "Chaincraft v0.7.0 - Córdoba" --notes-file CHANGELOG.md
```

The workflow will automatically trigger and publish the package to PyPI.

## Manual Publishing (Alternative)

If you prefer manual publishing or need to publish without a release:

```bash
# Install build tools
pip install build twine

# Build the package
python -m build

# Upload to PyPI (requires API token)
twine upload dist/*
```

## Package Structure

The package is structured as follows:

```
chaincraft/
├── chaincraft/                     # Main package source
│   ├── __init__.py                 # Package initialization and exports
│   ├── node.py                     # Main ChaincraftNode class
│   ├── shared_object.py            # SharedObject base class
│   ├── shared_message.py           # SharedMessage class
│   ├── index_helper.py             # IndexHelper class
│   └── crypto_primitives/          # Cryptographic primitives subpackage
│       ├── __init__.py
│       ├── pow.py                  # Proof of Work
│       ├── vdf.py                  # Verifiable Delay Function
│       ├── sign.py                 # ECDSA Signatures
│       ├── vrf.py                  # Verifiable Random Function
│       ├── encrypt.py              # Symmetric Encryption
│       ├── address.py              # Address generation
│       └── abstract.py             # Abstract base classes
├── chaincraft_cli.py              # CLI entry point
├── pyproject.toml                 # Package configuration
├── MANIFEST.in                    # Additional files to include
└── README.md                      # Package documentation
```

## Installation After Publishing

Once published, users can install the package with:

```bash
pip install chaincraft
```

And use it in their code:

```python
import chaincraft

# Create a node
node = chaincraft.ChaincraftNode()
node.start()

# Use crypto primitives
from chaincraft.crypto_primitives.pow import ProofOfWorkPrimitive
pow_primitive = ProofOfWorkPrimitive()

# Use the CLI
# chaincraft-cli --help
```

## Troubleshooting

### Common Issues

1. **Import Errors**: Make sure all relative imports use the correct syntax (`.module`)
2. **Package Not Found**: Verify the package structure in `pyproject.toml`
3. **CLI Not Working**: Ensure `chaincraft_cli.py` is included in `py-modules`

### Testing Locally

Before publishing, test the package locally:

```bash
# Install in development mode
pip install -e .

# Test imports
python -c "import chaincraft; print(chaincraft.__version__)"

# Test CLI
chaincraft-cli --help
```

## Security Notes

- Never commit API tokens to the repository
- Use trusted publishing when possible
- Review the workflow permissions carefully
- Consider using environment protection rules for production releases
