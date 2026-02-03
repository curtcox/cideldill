"""Logger module for CID el Dill."""

from typing import Any, Optional


class Logger:
    """Logger for execution tracking.

    This class provides logging functionality to track execution
    and send data to a remote inspector/debugger.

    Attributes:
        name: The name of the logger instance.
        level: The logging level.
    """

    def __init__(self, name: str, level: str = "INFO") -> None:
        """Initialize the Logger.

        Args:
            name: The name of the logger.
            level: The logging level (default: "INFO").
        """
        self.name = name
        self.level = level
        self._messages: list[dict[str, Any]] = []

    def log(self, message: str, data: Optional[dict[str, Any]] = None) -> None:
        """Log a message with optional data.

        Args:
            message: The message to log.
            data: Optional dictionary of additional data.
        """
        entry: dict[str, Any] = {"message": message, "level": self.level}
        if data:
            entry["data"] = data
        self._messages.append(entry)

    def get_messages(self) -> list[dict[str, Any]]:
        """Get all logged messages.

        Returns:
            A list of all logged messages.
        """
        return self._messages.copy()

    def clear(self) -> None:
        """Clear all logged messages."""
        self._messages.clear()
