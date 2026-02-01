# Examples

Progressive demo applications for development, documentation, and demonstration of the CID el Dill debugger.

## Design Principles

- Each level should be a single file (or two for async)
- Each level exercises one or two new capabilities
- Examples should be realistic enough to be instructive, but minimal
- Same example can serve as: unit test fixture, documentation, demo
- No NAT dependency until level 6

## Available Examples

### Level 0: Calculator ✅

**File**: `level0_calculator.py`  
**Tests**: `tests/examples/test_level0_calculator.py`  
**Status**: Complete

**Purpose**: Verify basic interception and CAS storage of primitives.

**Functions**:
- `add(a: int, b: int) -> int` - Add two integers
- `mul(a: int, b: int) -> int` - Multiply two integers
- `div(a: int, b: int) -> int` - Integer division (can raise ZeroDivisionError)

**Test Coverage**:
- Basic arithmetic operations
- Edge cases (negative numbers, zero, division by zero)
- Nested function calls
- CID stability (same args → same result)

**Running the Example**:
```bash
python examples/level0_calculator.py
```

**Running the Tests**:
```bash
pytest tests/examples/test_level0_calculator.py -v
```

## Future Levels

See `todo/examples_plan.md` for details on upcoming example levels:

- **Level 1**: Calculator with State (dataclass serialization, CID references)
- **Level 2**: File Processor (larger payloads, unpicklable edge cases)
- **Level 3**: Tool Dispatcher (dynamic resolution, builder pattern)
- **Level 4**: Async Tool Dispatcher (async interception, concurrent calls)
- **Level 5**: Mock Agent Loop (multi-step call chains, breakpoints)
- **Level 6**: NAT App (real integration with NVIDIA Nemo Agent Toolkit)

## Development Approach

All examples are developed using Test-Driven Development (TDD):

1. Write tests first (red phase)
2. Implement minimal code to pass tests (green phase)
3. Refactor and improve (refactor phase)
4. Ensure code quality with linters (ruff, pylint, mypy)

## Contributing

When adding new examples:

1. Follow the design principles above
2. Create comprehensive test coverage
3. Document purpose and usage
4. Update this README
5. Update `todo/examples_plan.md` with progress
