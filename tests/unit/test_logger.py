"""Unit tests for Logger class."""

from cideldill.logger import Logger


def test_logger_initialization() -> None:
    """Test Logger initialization."""
    logger = Logger("test")
    assert logger.name == "test"
    assert logger.level == "INFO"


def test_logger_with_custom_level() -> None:
    """Test Logger with custom level."""
    logger = Logger("test", level="DEBUG")
    assert logger.level == "DEBUG"


def test_log_message() -> None:
    """Test logging a message."""
    logger = Logger("test")
    logger.log("Test message")
    messages = logger.get_messages()
    assert len(messages) == 1
    assert messages[0]["message"] == "Test message"


def test_log_with_data() -> None:
    """Test logging with additional data."""
    logger = Logger("test")
    logger.log("Test message", {"key": "value"})
    messages = logger.get_messages()
    assert messages[0]["data"]["key"] == "value"


def test_clear_messages() -> None:
    """Test clearing messages."""
    logger = Logger("test")
    logger.log("Test message")
    logger.clear()
    assert len(logger.get_messages()) == 0
