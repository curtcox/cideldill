#!/usr/bin/env bash
# Install dependencies for CID el Dill
#
# Usage:
#   ./install_deps.sh              # Install runtime dependencies only
#   ./install_deps.sh --dev        # Install development dependencies

set -e

echo "Installing CID el Dill dependencies..."

if [ "$1" = "--dev" ]; then
    echo "Installing with development dependencies..."
    pip install -e ".[dev]"
else
    echo "Installing runtime dependencies only..."
    pip install -e .
fi

echo ""
echo "✓ Dependencies installed successfully!"
echo ""
echo "To verify installation, run:"
echo "  python -c 'import cideldill; print(\"CID el Dill version:\", cideldill.__version__ if hasattr(cideldill, \"__version__\") else \"unknown\")'"
