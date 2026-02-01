#!/bin/bash
# Build script for CID el Dill project

set -e

echo "Building CID el Dill..."

# Install dependencies
if [ -f "pyproject.toml" ]; then
    echo "Installing Python dependencies..."
    pip install -e ".[dev]"
fi

# Run linters
echo "Running linters..."
ruff check src/ || true
pylint src/ || true

# Run tests
echo "Running tests..."
pytest

echo "Build complete!"
