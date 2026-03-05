#!/bin/sh

# Install build tools
apk add --update --no-cache py3-twine py3-setuptools py3-wheel py3-pip py3-build

# Clean any existing build artifacts
rm -rf build dist *.egg-info

# Build the package
python -m build

# Upload to PyPI
# Get version from setup.py
VERSION=$(python setup.py --version)
twine upload dist/madblog-${VERSION}.tar.gz dist/madblog-${VERSION}-py3-none-any.whl