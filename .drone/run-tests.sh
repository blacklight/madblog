#!/bin/sh

# Install system dependencies
apk add --update --no-cache gcc musl-dev libffi-dev libxml2-dev libxslt-dev

# Install Python dependencies
pip install --break-system-packages .
pip install --break-system-packages pytest

# Run tests
pytest tests/