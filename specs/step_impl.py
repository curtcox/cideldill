"""Step implementations for Gauge tests."""

from getgauge.python import step
from cideldill_client.logger import Logger

# Logger steps
_logger = None


@step("Create a logger with name <name>")
def create_logger(name):
    """Create a logger instance."""
    global _logger
    _logger = Logger(name)


@step("Logger name should be <name>")
def check_logger_name(name):
    """Check logger name."""
    assert _logger.name == name


@step("Log message <message>")
def log_message(message):
    """Log a message."""
    _logger.log(message)


@step("Logger should have <count> messages")
def check_message_count(count):
    """Check message count."""
    assert len(_logger.get_messages()) == int(count)


@step("Clear all messages")
def clear_messages():
    """Clear all messages."""
    _logger.clear()
