"""Sequence Demo Example.

This example demonstrates remote debugging capabilities with configurable
sequence, announce, and delay functions. It provides a useful sample app for
testing and validating breakpoints and other related remote configuration abilities.

Purpose:
    - Demonstrate with_debug wrapping of various function types
    - Provide configurable behaviors for testing different scenarios
    - Test remote debugging and configuration with repeating operations

Functions:
    - Sequence functions: whole numbers, multiples of 2/3, primes, composites
    - Announce functions: print, log, say with different voices
    - Delay functions: 0.1s, 1s, 10s, 100s
"""

import argparse
import logging
import platform
import subprocess
import sys
import time
from typing import Callable, Optional

from cideldill import with_debug

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


# Sequence Functions
def whole_numbers(n: int) -> int:
    """Return the next whole number.

    Args:
        n: Current number

    Returns:
        n + 1
    """
    return n + 1


def multiples_of_2(n: int) -> int:
    """Return the next multiple of 2.

    Args:
        n: Current number

    Returns:
        n + 2
    """
    return n + 2


def multiples_of_3(n: int) -> int:
    """Return the next multiple of 3.

    Args:
        n: Current number

    Returns:
        n + 3
    """
    return n + 3


def _is_prime(n: int) -> bool:
    """Check if a number is prime.

    Args:
        n: Number to check

    Returns:
        True if n is prime, False otherwise
    """
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    for i in range(3, int(n ** 0.5) + 1, 2):
        if n % i == 0:
            return False
    return True


def primes(n: int) -> int:
    """Return the next prime number greater than n.

    Args:
        n: Current number

    Returns:
        Next prime after n
    """
    candidate = n + 1
    while not _is_prime(candidate):
        candidate += 1
    return candidate


def composites(n: int) -> int:
    """Return the next composite number greater than n.

    Args:
        n: Current number

    Returns:
        Next composite after n (skipping primes and 0, 1)
    """
    candidate = max(n + 1, 4)  # Start at 4, first composite
    while _is_prime(candidate):
        candidate += 1
    return candidate


# Announce Functions
def announce_print(value: int) -> None:
    """Announce value using print.

    Args:
        value: Value to announce
    """
    print(f"Value: {value}")


def announce_log(value: int) -> None:
    """Announce value using logging.

    Args:
        value: Value to announce
    """
    logger.info("Value: %d", value)


def announce_say_default(value: int) -> None:
    """Announce value using Mac 'say' command with default voice.

    Args:
        value: Value to announce
    """
    if platform.system() != "Darwin":
        announce_print(value)
        return
    try:
        subprocess.run(["say", str(value)], check=False, capture_output=True)
    except (FileNotFoundError, subprocess.SubprocessError):
        announce_print(value)


def announce_say_alex(value: int) -> None:
    """Announce value using Mac 'say' command with Alex voice.

    Args:
        value: Value to announce
    """
    if platform.system() != "Darwin":
        announce_print(value)
        return
    try:
        subprocess.run(["say", "-v", "Alex", str(value)], check=False, capture_output=True)
    except (FileNotFoundError, subprocess.SubprocessError):
        announce_print(value)


def announce_say_samantha(value: int) -> None:
    """Announce value using Mac 'say' command with Samantha voice.

    Args:
        value: Value to announce
    """
    if platform.system() != "Darwin":
        announce_print(value)
        return
    try:
        subprocess.run(["say", "-v", "Samantha", str(value)], check=False, capture_output=True)
    except (FileNotFoundError, subprocess.SubprocessError):
        announce_print(value)


def announce_say_victoria(value: int) -> None:
    """Announce value using Mac 'say' command with Victoria voice.

    Args:
        value: Value to announce
    """
    if platform.system() != "Darwin":
        announce_print(value)
        return
    try:
        subprocess.run(["say", "-v", "Victoria", str(value)], check=False, capture_output=True)
    except (FileNotFoundError, subprocess.SubprocessError):
        announce_print(value)


# Delay Functions
def delay_01s() -> None:
    """Delay for 0.1 seconds."""
    time.sleep(0.1)


def delay_1s() -> None:
    """Delay for 1 second."""
    time.sleep(1.0)


def delay_10s() -> None:
    """Delay for 10 seconds."""
    time.sleep(10.0)


def delay_100s() -> None:
    """Delay for 100 seconds."""
    time.sleep(100.0)


def run_sequence(
    sequence_fn: Callable[[int], int],
    announce_fn: Callable[[int], None],
    delay_fn: Callable[[], None],
    iterations: int = 10,
    initial_value: int = 0
) -> None:
    """Run the sequence demo with the given configuration.

    Args:
        sequence_fn: Function that generates the next value
        announce_fn: Function that announces the value
        delay_fn: Function that introduces delay between iterations
        iterations: Number of iterations to run (default: 10)
        initial_value: Starting value (default: 0)
    """
    value = initial_value
    for _ in range(iterations):
        value = sequence_fn(value)
        announce_fn(value)
        delay_fn()


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Command-line arguments (default: sys.argv[1:])

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description="Run the sequence demo with configurable debugging and iterations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  sequence_demo.py                           # Run with defaults (debug=OFF, iterations=10)
  sequence_demo.py --debug ON                # Enable debugging
  sequence_demo.py --iterations 20           # Run 20 iterations
  sequence_demo.py -d ON -i 5                # Enable debugging with 5 iterations
        """
    )

    parser.add_argument(
        "--debug", "-d",
        default="OFF",
        choices=["ON", "OFF"],
        help="Enable or disable debugging (default: OFF)"
    )

    parser.add_argument(
        "--iterations", "-i",
        type=int,
        default=10,
        help="Number of iterations to run (default: 10)"
    )

    return parser.parse_args(argv)


def main() -> None:
    """Run the sequence demo with command-line configurable options."""
    # Parse command-line arguments
    args = parse_args()

    # Configure debugging based on command-line argument
    with_debug(args.debug)

    # Wrap functions with with_debug
    sequence_fn = with_debug(whole_numbers)
    announce_fn = with_debug(announce_say_default)
    delay_fn = with_debug(delay_1s)

    print("Starting sequence demo with configuration:")
    print("- Sequence: whole numbers")
    print("- Announce: say (default voice)")
    print("- Delay: 1 second")
    print(f"- Iterations: {args.iterations}")
    print(f"- Debug: {args.debug}")
    print()

    run_sequence(sequence_fn, announce_fn, delay_fn, iterations=args.iterations, initial_value=0)


if __name__ == "__main__":
    main()
