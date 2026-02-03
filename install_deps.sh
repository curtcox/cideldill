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
echo "Installing CID el Dill client/server dependencies..."
echo ""

# Determine install targets
if [ "$1" = "--dev" ]; then
    CLIENT_TARGET="client[dev]"
    SERVER_TARGET="server[dev]"
else
    CLIENT_TARGET="client"
    SERVER_TARGET="server"
fi

# Check if we're in a virtual environment
if [ -z "$VIRTUAL_ENV" ]; then
    # Not in a virtual environment
    # Try installing without --user first, fall back to --user if externally managed
    echo "Note: Not in a virtual environment."
    echo "Attempting system installation..."
    echo ""
    
    if [ "$1" = "--dev" ]; then
        if ! $PYTHON_CMD -m pip install -e "$CLIENT_TARGET" -e "$SERVER_TARGET" 2>/dev/null; then
            echo ""
            echo "System installation failed (externally-managed environment)."
            echo "Installing to user site-packages with --user flag..."
            echo ""
            $PYTHON_CMD -m pip install --user -e "$CLIENT_TARGET" -e "$SERVER_TARGET"
        fi
    else
        if ! $PYTHON_CMD -m pip install -e "$CLIENT_TARGET" -e "$SERVER_TARGET" 2>/dev/null; then
            echo ""
            echo "System installation failed (externally-managed environment)."
            echo "Installing to user site-packages with --user flag..."
            echo ""
            $PYTHON_CMD -m pip install --user -e "$CLIENT_TARGET" -e "$SERVER_TARGET"
        fi
    fi
else
    # In a virtual environment, install normally
    echo "Installing in virtual environment: $VIRTUAL_ENV"
    echo ""
    
    $PYTHON_CMD -m pip install -e "$CLIENT_TARGET" -e "$SERVER_TARGET"
fi

echo ""
echo "✓ Dependencies installed successfully!"
echo ""
echo "Installed package locations:"
$PYTHON_CMD -m pip show cideldill-client 2>/dev/null | grep "Location:" || echo "  (Unable to determine location for cideldill-client)"
$PYTHON_CMD -m pip show cideldill-server 2>/dev/null | grep "Location:" || echo "  (Unable to determine location for cideldill-server)"
echo ""
echo "To verify installation, run:"
echo "  $PYTHON_CMD doctor.py"
