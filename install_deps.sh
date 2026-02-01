#!/usr/bin/env bash
# Install dependencies for CID el Dill
#
# Usage:
#   ./install_deps.sh              # Install runtime dependencies only
#   ./install_deps.sh --dev        # Install development dependencies

set -e

# Determine which Python to use
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "Error: Python not found. Please install Python 3.9 or higher."
    exit 1
fi

echo "Using Python: $PYTHON_CMD ($($PYTHON_CMD --version))"
echo "Python executable: $($PYTHON_CMD -c 'import sys; print(sys.executable)')"
echo "Installing CID el Dill dependencies..."
echo ""

if [ "$1" = "--dev" ]; then
    echo "Installing with development dependencies..."
    $PYTHON_CMD -m pip install -e ".[dev]"
else
    echo "Installing runtime dependencies only..."
    $PYTHON_CMD -m pip install -e .
fi

echo ""
echo "✓ Dependencies installed successfully!"
echo ""
echo "Installed package location:"
$PYTHON_CMD -m pip show cideldill 2>/dev/null | grep "Location:" || echo "  (Unable to determine location)"
echo ""
echo "To verify installation, run:"
echo "  $PYTHON_CMD doctor.py"
