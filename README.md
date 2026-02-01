# CID el Dill

CID el Dill is a Python library for logging execution to a remote inspector/debugger/configuration agent.

## Features

- **Logger**: Track and log execution events with structured data
- **Inspector**: Remote debugging and configuration through an agent
- **Comprehensive Testing**: Unit tests, property-based tests with Hypothesis, and more
- **Code Quality**: Automated linting and quality checks with multiple tools

## Installation

```bash
pip install -e .
```

For development:

```bash
pip install -e ".[dev]"
```

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
- **Frontend**: ESLint, Stylelint, UNCSS
- **Testing**: Unit tests, Coverage, Hypothesis property tests
- **Gauge**: Acceptance tests

View the latest build report at: https://curtcox.github.io/cideldill/

## License

MIT
