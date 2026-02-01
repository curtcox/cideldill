# CID el Dill

[![Build Report](https://github.com/curtcox/cideldill/actions/workflows/build-report.yml/badge.svg)](https://github.com/curtcox/cideldill/actions/workflows/build-report.yml)

CID el Dill is a Python library for logging execution to a remote inspector/debugger/configuration agent.

## Features

- **Logger**: Track and log execution events with structured data
- **Inspector**: Remote debugging and configuration through an agent
- **Comprehensive Testing**: Unit tests, property-based tests with Hypothesis, and more
- **Code Quality**: Automated linting and quality checks with multiple tools

## Installation

### Quick Start

To install CID el Dill with all dependencies:

```bash
./install_deps.sh
```

For development (includes testing and linting tools):

```bash
./install_deps.sh --dev
```

**Important**: The install script uses `python3` by default. Make sure you run the doctor script and examples with the same Python version.

### Verify Installation

After installation, verify everything is working correctly:

```bash
python3 doctor.py
```

This will check:
- Python version compatibility
- CID el Dill package installation
- All required dependencies (including Pygments)
- Optional development dependencies

If the doctor script reports issues, ensure you're using the same Python version for both installation and running scripts.

### Manual Installation

Alternatively, you can install manually using pip:

```bash
pip install -e .
```

For development:

```bash
pip install -e ".[dev]"
```

### Running Examples

After installation, you can run the examples:

```bash
./run/mac/calculator_example
```

**Note**: The examples require the package to be installed first (via `./install_deps.sh`) to ensure all dependencies (including `pygments` for syntax-highlighted HTML reports) are available.

## Usage

### Logger

```python
from cideldill import Logger

logger = Logger("my-app")
logger.log("Application started", {"version": "1.0.0"})
messages = logger.get_messages()
```

### Inspector

```python
from cideldill import Inspector

inspector = Inspector("localhost", 8080)
inspector.connect()
inspector.send_data({"event": "startup", "timestamp": "2024-01-01"})
inspector.disconnect()
```

## Development

### Running Tests

```bash
pytest
```

### Running Linters

```bash
ruff check src/
pylint src/
mypy src/
```

### Building Reports

Build reports are automatically generated on every push to main and published to GitHub Pages.

## Build Reports

This project generates comprehensive build reports including:

- **Python Quality**: Ruff, Pylint, Mypy, Pydoclint
- **Code Metrics**: Radon (complexity & maintainability), Vulture
- **Shell & Docker**: ShellCheck, Hadolint
- **Frontend**: ESLint, Stylelint
- **Testing**: Unit tests, Coverage, Hypothesis property tests, Gauge acceptance tests

### Viewing Build Reports

Build reports are automatically generated on every push to the main branch and published to GitHub Pages.

View the latest build report at: https://curtcox.github.io/cideldill/

### Setting Up GitHub Pages (First Time)

To enable GitHub Pages for this repository:

1. Go to the repository Settings
2. Navigate to "Pages" in the left sidebar
3. Under "Build and deployment":
   - Source: Select "GitHub Actions"
4. The workflow will automatically deploy on the next push to main

## License

MIT
