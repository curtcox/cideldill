"""Unit tests for sequence_demo_breakpoints script."""

import os
from pathlib import Path


def test_script_exists() -> None:
    """Test that the sequence_demo_breakpoints script exists."""
    script_path = Path(__file__).parent.parent.parent / "run" / "mac" / "sequence_demo_breakpoints"
    assert script_path.exists(), f"Script not found at {script_path}"


def test_script_is_executable() -> None:
    """Test that the sequence_demo_breakpoints script is executable."""
    script_path = Path(__file__).parent.parent.parent / "run" / "mac" / "sequence_demo_breakpoints"
    assert os.access(script_path, os.X_OK), f"Script is not executable: {script_path}"


def test_script_has_shebang() -> None:
    """Test that the script has proper shebang."""
    script_path = Path(__file__).parent.parent.parent / "run" / "mac" / "sequence_demo_breakpoints"
    with open(script_path, "r", encoding="utf-8") as f:
        first_line = f.readline()
    assert first_line.startswith("#!"), f"Script missing shebang: {first_line}"
    assert "python" in first_line.lower(), f"Script should use Python: {first_line}"
