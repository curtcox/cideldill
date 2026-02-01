"""Unit tests for Level 0 Calculator example.

This test suite validates the basic calculator functions and their behaviors,
including exception handling for division by zero.
"""

import pytest
from examples.level0_calculator import add, div, mul


def test_add_basic() -> None:
    """Test basic addition operation."""
    result = add(2, 3)
    assert result == 5


def test_add_negative_numbers() -> None:
    """Test addition with negative numbers."""
    result = add(-5, 3)
    assert result == -2


def test_add_zero() -> None:
    """Test addition with zero."""
    result = add(0, 5)
    assert result == 5


def test_mul_basic() -> None:
    """Test basic multiplication operation."""
    result = mul(4, 5)
    assert result == 20


def test_mul_by_zero() -> None:
    """Test multiplication by zero."""
    result = mul(5, 0)
    assert result == 0


def test_mul_negative() -> None:
    """Test multiplication with negative numbers."""
    result = mul(-2, 3)
    assert result == -6


def test_div_basic() -> None:
    """Test basic division operation."""
    result = div(10, 2)
    assert result == 5


def test_div_integer_division() -> None:
    """Test integer division behavior."""
    result = div(7, 2)
    assert result == 3  # Integer division


def test_div_by_zero_raises_exception() -> None:
    """Test that division by zero raises ZeroDivisionError."""
    with pytest.raises(ZeroDivisionError):
        div(1, 0)


def test_nested_calls() -> None:
    """Test nested function calls: mul(add(2, 3), 4) should equal 20."""
    inner_result = add(2, 3)
    result = mul(inner_result, 4)
    assert result == 20


def test_nested_calls_inline() -> None:
    """Test nested function calls inline: mul(add(2, 3), 4) should equal 20."""
    result = mul(add(2, 3), 4)
    assert result == 20


def test_add_with_same_args_returns_same_result() -> None:
    """Test that calling add with same args returns the same result.

    This verifies CID stability concept - same args should produce same result.
    """
    result1 = add(2, 3)
    result2 = add(2, 3)
    assert result1 == result2
    assert result1 == 5


def test_mul_with_same_args_returns_same_result() -> None:
    """Test that calling mul with same args returns the same result.

    This verifies CID stability concept - same args should produce same result.
    """
    result1 = mul(4, 5)
    result2 = mul(4, 5)
    assert result1 == result2
    assert result1 == 20
