# GitHub Copilot Instructions for CID el Dill

## Project Overview

CID el Dill is a Python library for logging execution to a remote inspector/debugger/configuration agent. The project emphasizes code quality, comprehensive testing, and automated reporting.

## Technology Stack

- **Language**: Python 3.9+
- **Build System**: setuptools
- **Package Manager**: pip
- **Testing**: pytest, pytest-cov, hypothesis (property-based testing)
- **Code Quality**: ruff, pylint, mypy, pydoclint
- **Code Analysis**: radon (complexity & maintainability), vulture
- **Frontend**: ESLint, Stylelint (for static assets)
- **Shell**: ShellCheck
- **Docker**: Hadolint

## Project Structure

```
src/cideldill/          # Main source code
  ├── logger.py         # Logging functionality
  ├── inspector.py      # Remote debugging/configuration
  ├── interceptor.py    # Execution interception
  └── cas_store.py      # Content-addressable storage
tests/
  ├── unit/            # Unit tests
  ├── integration/     # Integration tests
  └── examples/        # Example-based tests
examples/              # Usage examples
specs/                 # Gauge acceptance tests
```

## Development Workflow

### Installation

```bash
# Development installation with all dependencies
pip install -e ".[dev]"
```

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=cideldill

# Run specific test file
pytest tests/unit/test_logger.py
```

### Code Quality

Run these linters before committing:

```bash
# Format and lint with ruff
ruff check src/

# Type checking
mypy src/

# Additional linting
pylint src/

# Docstring linting
pydoclint src/
```

## Coding Standards

### Python Style

- Follow PEP 8 conventions
- Use type hints for all function signatures
- Write comprehensive docstrings for all public APIs
- Maintain test coverage above 80%
- Keep cyclomatic complexity low (monitored by radon)

### Testing Requirements

- Write unit tests for all new functionality
- Add property-based tests with hypothesis for complex logic
- Include integration tests for component interactions
- Update examples when adding new features

### Code Quality Checks

All code must pass:
- ruff (formatter and linter)
- pylint (static analysis)
- mypy (type checking)
- pydoclint (docstring validation)

### Commit Practices

- Make small, focused commits
- Write clear commit messages
- Ensure all tests pass before pushing
- Maintain clean git history

## Key Files to Know

- `pyproject.toml` - Project configuration and dependencies (includes `[tool.pytest]` test configuration)
- `.eslintrc.json` - JavaScript linting rules
- `.stylelintrc.json` - CSS linting rules
- `Dockerfile` - Container configuration
- `manifest.json` - Web manifest

## Common Tasks

### Adding a New Feature

1. Create tests first (TDD approach)
2. Implement the feature in `src/cideldill/`
3. Run tests: `pytest`
4. Run linters: `ruff check src/ && pylint src/ && mypy src/`
5. Update documentation if needed
6. Add examples if appropriate

### Fixing a Bug

1. Write a failing test that reproduces the bug
2. Fix the bug
3. Verify the test passes
4. Run full test suite
5. Run linters

### Adding Dependencies

- Add runtime dependencies to `dependencies` in `pyproject.toml`
- Add development dependencies to `dev` under `[project.optional-dependencies]`
- Run `pip install -e ".[dev]"` to install new dependencies

## Build Reports

The project automatically generates comprehensive build reports on every push to main, including:
- Python quality metrics
- Code complexity and maintainability
- Test coverage
- Linting results

Reports are published to GitHub Pages at: https://curtcox.github.io/cideldill/

## Important Notes

- This project uses property-based testing with hypothesis - leverage it for testing complex logic
- All code changes trigger automated quality checks via GitHub Actions
- The project follows semantic versioning
- Frontend assets (if any) must pass ESLint and Stylelint checks
- Shell scripts must pass ShellCheck validation
- Dockerfiles must pass Hadolint validation
