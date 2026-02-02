"""Unit tests for Sequence Demo example.

This test suite validates the sequence, announce, and delay functions,
as well as the overall sequence execution logic.
"""

import logging
import sys
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from examples.sequence_demo import (
    _is_prime,
    announce_log,
    announce_print,
    announce_say_alex,
    announce_say_default,
    announce_say_samantha,
    announce_say_victoria,
    composites,
    delay_01s,
    delay_1s,
    delay_10s,
    delay_100s,
    multiples_of_2,
    multiples_of_3,
    primes,
    run_sequence,
    whole_numbers,
)


# Sequence Function Tests
def test_whole_numbers() -> None:
    """Test whole numbers sequence."""
    assert whole_numbers(0) == 1
    assert whole_numbers(5) == 6
    assert whole_numbers(99) == 100


def test_multiples_of_2() -> None:
    """Test multiples of 2 sequence."""
    assert multiples_of_2(0) == 2
    assert multiples_of_2(2) == 4
    assert multiples_of_2(10) == 12


def test_multiples_of_3() -> None:
    """Test multiples of 3 sequence."""
    assert multiples_of_3(0) == 3
    assert multiples_of_3(3) == 6
    assert multiples_of_3(9) == 12


def test_is_prime() -> None:
    """Test prime number detection."""
    assert not _is_prime(0)
    assert not _is_prime(1)
    assert _is_prime(2)
    assert _is_prime(3)
    assert not _is_prime(4)
    assert _is_prime(5)
    assert not _is_prime(6)
    assert _is_prime(7)
    assert not _is_prime(8)
    assert not _is_prime(9)
    assert not _is_prime(10)
    assert _is_prime(11)
    assert _is_prime(13)
    assert _is_prime(17)
    assert _is_prime(19)
    assert not _is_prime(20)
    assert not _is_prime(100)


def test_primes() -> None:
    """Test prime number sequence."""
    assert primes(0) == 2
    assert primes(2) == 3
    assert primes(3) == 5
    assert primes(5) == 7
    assert primes(7) == 11
    assert primes(10) == 11
    assert primes(11) == 13


def test_composites() -> None:
    """Test composite number sequence."""
    assert composites(0) == 4
    assert composites(4) == 6
    assert composites(6) == 8
    assert composites(8) == 9
    assert composites(9) == 10
    assert composites(10) == 12


# Announce Function Tests
def test_announce_print(capsys: Any) -> None:
    """Test print announcement."""
    announce_print(42)
    captured = capsys.readouterr()
    assert "Value: 42" in captured.out


def test_announce_log(caplog: Any) -> None:
    """Test log announcement."""
    with caplog.at_level(logging.INFO):
        announce_log(42)
    assert "Value: 42" in caplog.text


@patch("platform.system")
@patch("subprocess.run")
def test_announce_say_default_on_mac(mock_run: Any, mock_system: Any) -> None:
    """Test say announcement with default voice on Mac."""
    mock_system.return_value = "Darwin"
    announce_say_default(42)
    mock_run.assert_called_once()
    assert mock_run.call_args[0][0] == ["say", "42"]


@patch("platform.system")
def test_announce_say_default_not_on_mac(mock_system: Any, capsys: Any) -> None:
    """Test say announcement falls back to print on non-Mac systems."""
    mock_system.return_value = "Linux"
    announce_say_default(42)
    captured = capsys.readouterr()
    assert "Value: 42" in captured.out


@patch("platform.system")
@patch("subprocess.run")
def test_announce_say_alex(mock_run: Any, mock_system: Any) -> None:
    """Test say announcement with Alex voice."""
    mock_system.return_value = "Darwin"
    announce_say_alex(42)
    mock_run.assert_called_once()
    assert mock_run.call_args[0][0] == ["say", "-v", "Alex", "42"]


@patch("platform.system")
@patch("subprocess.run")
def test_announce_say_samantha(mock_run: Any, mock_system: Any) -> None:
    """Test say announcement with Samantha voice."""
    mock_system.return_value = "Darwin"
    announce_say_samantha(42)
    mock_run.assert_called_once()
    assert mock_run.call_args[0][0] == ["say", "-v", "Samantha", "42"]


@patch("platform.system")
@patch("subprocess.run")
def test_announce_say_victoria(mock_run: Any, mock_system: Any) -> None:
    """Test say announcement with Victoria voice."""
    mock_system.return_value = "Darwin"
    announce_say_victoria(42)
    mock_run.assert_called_once()
    assert mock_run.call_args[0][0] == ["say", "-v", "Victoria", "42"]


@patch("platform.system")
@patch("subprocess.run")
def test_announce_say_handles_subprocess_error(mock_run: Any, mock_system: Any, capsys: Any) -> None:
    """Test say announcement handles subprocess errors."""
    mock_system.return_value = "Darwin"
    mock_run.side_effect = FileNotFoundError()
    announce_say_default(42)
    captured = capsys.readouterr()
    assert "Value: 42" in captured.out


# Delay Function Tests
def test_delay_01s() -> None:
    """Test 0.1 second delay."""
    start = time.time()
    delay_01s()
    elapsed = time.time() - start
    assert 0.08 <= elapsed <= 0.15  # Allow some tolerance


def test_delay_1s() -> None:
    """Test 1 second delay."""
    start = time.time()
    delay_1s()
    elapsed = time.time() - start
    assert 0.9 <= elapsed <= 1.2  # Allow some tolerance


def test_delay_10s() -> None:
    """Test 10 second delay (mocked for speed)."""
    with patch("time.sleep") as mock_sleep:
        delay_10s()
        mock_sleep.assert_called_once_with(10.0)


def test_delay_100s() -> None:
    """Test 100 second delay (mocked for speed)."""
    with patch("time.sleep") as mock_sleep:
        delay_100s()
        mock_sleep.assert_called_once_with(100.0)


# Integration Tests
def test_run_sequence() -> None:
    """Test run_sequence integration."""
    sequence_fn = MagicMock(side_effect=lambda n: n + 1)
    announce_fn = MagicMock()
    delay_fn = MagicMock()

    run_sequence(sequence_fn, announce_fn, delay_fn, iterations=5, initial_value=0)

    assert sequence_fn.call_count == 5
    assert announce_fn.call_count == 5
    assert delay_fn.call_count == 5

    # Verify the sequence of values
    for i, call in enumerate(announce_fn.call_args_list):
        assert call[0][0] == i + 1


def test_run_sequence_with_whole_numbers(capsys: Any) -> None:
    """Test run_sequence with whole numbers and print."""
    run_sequence(whole_numbers, announce_print, lambda: None, iterations=3, initial_value=0)
    captured = capsys.readouterr()
    assert "Value: 1" in captured.out
    assert "Value: 2" in captured.out
    assert "Value: 3" in captured.out


def test_run_sequence_with_primes(capsys: Any) -> None:
    """Test run_sequence with primes."""
    run_sequence(primes, announce_print, lambda: None, iterations=3, initial_value=0)
    captured = capsys.readouterr()
    assert "Value: 2" in captured.out
    assert "Value: 3" in captured.out
    assert "Value: 5" in captured.out


def test_run_sequence_with_composites(capsys: Any) -> None:
    """Test run_sequence with composites."""
    run_sequence(composites, announce_print, lambda: None, iterations=3, initial_value=0)
    captured = capsys.readouterr()
    assert "Value: 4" in captured.out
    assert "Value: 6" in captured.out
    assert "Value: 8" in captured.out


def test_sequence_consistency() -> None:
    """Test that sequence functions return consistent results."""
    # Same input should produce same output
    assert whole_numbers(5) == whole_numbers(5)
    assert multiples_of_2(10) == multiples_of_2(10)
    assert primes(7) == primes(7)
    assert composites(9) == composites(9)


# Command-line Interface Tests
def test_parse_args_default() -> None:
    """Test parse_args with default values."""
    from examples.sequence_demo import parse_args
    
    args = parse_args([])
    assert args.debug == "OFF"
    assert args.iterations == 10


def test_parse_args_debug_on() -> None:
    """Test parse_args with debug flag ON."""
    from examples.sequence_demo import parse_args
    
    args = parse_args(["--debug", "ON"])
    assert args.debug == "ON"
    assert args.iterations == 10


def test_parse_args_debug_off() -> None:
    """Test parse_args with debug flag OFF."""
    from examples.sequence_demo import parse_args
    
    args = parse_args(["--debug", "OFF"])
    assert args.debug == "OFF"
    assert args.iterations == 10


def test_parse_args_iterations() -> None:
    """Test parse_args with custom iterations."""
    from examples.sequence_demo import parse_args
    
    args = parse_args(["--iterations", "20"])
    assert args.debug == "OFF"
    assert args.iterations == 20


def test_parse_args_debug_and_iterations() -> None:
    """Test parse_args with both debug and iterations."""
    from examples.sequence_demo import parse_args
    
    args = parse_args(["--debug", "ON", "--iterations", "5"])
    assert args.debug == "ON"
    assert args.iterations == 5


def test_parse_args_short_flags() -> None:
    """Test parse_args with short flags."""
    from examples.sequence_demo import parse_args
    
    args = parse_args(["-d", "ON", "-i", "15"])
    assert args.debug == "ON"
    assert args.iterations == 15


def test_main_with_args(capsys: Any) -> None:
    """Test main function accepts CLI arguments."""
    from examples.sequence_demo import main
    
    # Mock with_debug to avoid server connection
    with patch("examples.sequence_demo.with_debug") as mock_with_debug:
        with patch("examples.sequence_demo.run_sequence") as mock_run_sequence:
            # Simulate CLI args
            with patch("sys.argv", ["sequence_demo.py", "--debug", "ON", "--iterations", "3"]):
                main()
            
            # Verify with_debug was called with "ON"
            mock_with_debug.assert_called()
            
            # Verify run_sequence was called with iterations=3
            assert mock_run_sequence.call_args[1]["iterations"] == 3
