"""Hypothesis property-based tests for Logger."""

from hypothesis import given, strategies as st
from cideldill.logger import Logger


@given(st.text(min_size=1), st.text())
def test_logger_accepts_any_name_and_level(name: str, level: str) -> None:
    """Test that Logger accepts any string name and level."""
    logger = Logger(name, level)
    assert logger.name == name
    assert logger.level == level


@given(st.text(), st.dictionaries(st.text(), st.text()))
def test_log_with_arbitrary_data(message: str, data: dict[str, str]) -> None:
    """Test logging with arbitrary data."""
    logger = Logger("test")
    logger.log(message, data)
    messages = logger.get_messages()
    assert len(messages) == 1
    assert messages[0]["message"] == message


@given(st.lists(st.text(), min_size=0, max_size=100))
def test_multiple_logs(messages: list[str]) -> None:
    """Test logging multiple messages."""
    logger = Logger("test")
    for msg in messages:
        logger.log(msg)
    retrieved = logger.get_messages()
    assert len(retrieved) == len(messages)
