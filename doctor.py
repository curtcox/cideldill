#!/usr/bin/env python3
"""Doctor Script - Validate CID el Dill Installation

This script checks that all required dependencies are properly installed
and that the environment is correctly configured.
"""

import sys

# ANSI color codes
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
RESET = '\033[0m'
BOLD = '\033[1m'


def check_python_version() -> tuple[bool, str]:
    """Check if Python version meets requirements."""
    required_version = (3, 9)
    current_version = sys.version_info[:2]

    if current_version >= required_version:
        return True, f"Python {sys.version.split()[0]}"
    else:
        return False, f"Python {sys.version.split()[0]} (requires >= 3.9)"


def check_module(module_name: str, import_name: str = None) -> tuple[bool, str]:
    """Check if a module is installed and importable."""
    if import_name is None:
        import_name = module_name

    try:
        __import__(import_name)
        return True, module_name
    except ImportError:
        return False, module_name


def check_cideldill_installed() -> tuple[bool, str]:
    """Check if cideldill package is properly installed."""
    try:
        import cideldill
        return True, f"cideldill (from {cideldill.__file__})"
    except ImportError:
        return False, "cideldill (NOT INSTALLED)"


def check_cideldill_components() -> list[tuple[bool, str]]:
    """Check if all cideldill components are accessible."""
    components = [
        ('CASStore', 'cideldill.cas_store'),
        ('Interceptor', 'cideldill.interceptor'),
        ('Logger', 'cideldill.logger'),
        ('Inspector', 'cideldill.inspector'),
        ('html_generator', 'cideldill.html_generator'),
        ('source_viewer', 'cideldill.source_viewer'),
    ]

    results = []
    for name, module in components:
        try:
            __import__(module)
            results.append((True, name))
        except ImportError as e:
            results.append((False, f"{name} ({str(e)})"))

    return results


def main():
    """Run all checks and report results."""
    print(f"{BOLD}CID el Dill Installation Doctor{RESET}")
    print("=" * 60)
    print(f"Using Python: {sys.executable}")
    print(f"Python path: {':'.join(sys.path[:3])}...")
    print()

    all_passed = True

    # Check Python version
    print(f"{BOLD}1. Python Version{RESET}")
    passed, msg = check_python_version()
    status = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
    print(f"   {status} {msg}")
    all_passed = all_passed and passed
    print()

    # Check cideldill installation
    print(f"{BOLD}2. CID el Dill Package{RESET}")
    passed, msg = check_cideldill_installed()
    status = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
    print(f"   {status} {msg}")
    all_passed = all_passed and passed
    print()

    # Check cideldill components
    print(f"{BOLD}3. CID el Dill Components{RESET}")
    component_results = check_cideldill_components()
    for passed, msg in component_results:
        status = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
        print(f"   {status} {msg}")
        all_passed = all_passed and passed
    print()

    # Check required dependencies
    print(f"{BOLD}4. Required Dependencies{RESET}")
    required_deps = [
        ('pygments', 'pygments'),
    ]

    for module_name, import_name in required_deps:
        passed, msg = check_module(module_name, import_name)
        status = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
        print(f"   {status} {msg}")
        all_passed = all_passed and passed
    print()

    # Check optional development dependencies
    print(f"{BOLD}5. Development Dependencies (Optional){RESET}")
    dev_deps = [
        ('pytest', 'pytest'),
        ('pytest-cov', 'pytest_cov'),
        ('hypothesis', 'hypothesis'),
        ('ruff', 'ruff'),
        ('pylint', 'pylint'),
        ('mypy', 'mypy'),
        ('pydoclint', 'pydoclint'),
        ('radon', 'radon'),
        ('vulture', 'vulture'),
    ]

    dev_all_installed = True
    for module_name, import_name in dev_deps:
        passed, msg = check_module(module_name, import_name)
        status = f"{GREEN}✓{RESET}" if passed else f"{YELLOW}○{RESET}"
        print(f"   {status} {msg}")
        dev_all_installed = dev_all_installed and passed
    print()

    # Summary
    print("=" * 60)
    if all_passed:
        print(f"{GREEN}{BOLD}✓ All required checks passed!{RESET}")
        print()
        print("Your CID el Dill installation is ready to use.")
        if not dev_all_installed:
            print()
            print(f"{YELLOW}Note: Some development dependencies are missing.{RESET}")
            print("To install them, run: ./install_deps.sh --dev")
    else:
        print(f"{RED}{BOLD}✗ Some checks failed.{RESET}")
        print()
        print("Common issues:")
        print("  1. Package installed with different Python version")
        print(f"     Current Python: {sys.executable}")
        print("     Solution: Run ./install_deps.sh to install for this Python")
        print()
        print("  2. Package not installed at all")
        print("     Solution: Run ./install_deps.sh")
        print()
        print("To install dependencies:")
        print("  ./install_deps.sh        # Runtime dependencies")
        print("  ./install_deps.sh --dev  # Development dependencies")
        sys.exit(1)

    print()
    print("To run examples:")
    print("  ./run/mac/calculator_example")


if __name__ == "__main__":
    main()
