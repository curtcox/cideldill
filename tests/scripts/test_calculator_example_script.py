"""Tests for the run/mac/calculator_example script.

This test suite validates that the calculator_example script:
1. Exists and is executable
2. Runs the calculator example with logging enabled
3. Creates a database with calculator execution data
4. Generates an HTML viewer for inspecting the database
5. Can open a browser to view the results
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def run_script_path():
    """Return the path to the calculator_example script."""
    repo_root = Path(__file__).parent.parent.parent
    script_path = repo_root / "run" / "mac" / "calculator_example"
    return script_path


@pytest.fixture
def temp_output_dir():
    """Create a temporary directory for script output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_script_exists(run_script_path):
    """Test that the calculator_example script exists."""
    assert run_script_path.exists(), f"Script not found at {run_script_path}"


def test_script_is_executable(run_script_path):
    """Test that the calculator_example script is executable."""
    assert os.access(run_script_path, os.X_OK), f"Script {run_script_path} is not executable"


def test_script_runs_without_browser(run_script_path, temp_output_dir):
    """Test that the script runs successfully without opening a browser."""
    # Run script with --no-browser flag to avoid opening browser during tests
    db_path = temp_output_dir / "test_calculator.db"
    html_path = temp_output_dir / "test_calculator.html"

    result = subprocess.run(
        [str(run_script_path), "--no-browser", "--db", str(db_path), "--output", str(html_path)],
        capture_output=True,
        text=True,
        timeout=10
    )

    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert db_path.exists(), f"Database not created at {db_path}"
    assert html_path.exists(), f"HTML output not created at {html_path}"


def test_script_creates_database_with_calculator_data(run_script_path, temp_output_dir):
    """Test that the script creates a database with calculator execution records."""
    db_path = temp_output_dir / "test_calculator.db"
    html_path = temp_output_dir / "test_calculator.html"

    # Run script
    subprocess.run(
        [str(run_script_path), "--no-browser", "--db", str(db_path), "--output", str(html_path)],
        capture_output=True,
        text=True,
        timeout=10,
        check=True
    )

    # Verify database contains calculator data
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Check that call_records table exists and has data
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='call_records'")
    assert cursor.fetchone() is not None, "call_records table not found"

    # Check that we have calculator function calls recorded
    cursor.execute("SELECT COUNT(*) FROM call_records")
    count = cursor.fetchone()[0]
    assert count > 0, "No call records found in database"

    # Check that we have add, mul, div function calls
    cursor.execute("SELECT DISTINCT function_name FROM call_records ORDER BY function_name")
    function_names = [row[0] for row in cursor.fetchall()]
    assert "add" in function_names, "No 'add' function calls found"
    assert "mul" in function_names, "No 'mul' function calls found"
    assert "div" in function_names, "No 'div' function calls found"

    conn.close()


def test_script_generates_html_viewer(run_script_path, temp_output_dir):
    """Test that the script generates an HTML viewer for the database."""
    db_path = temp_output_dir / "test_calculator.db"
    html_path = temp_output_dir / "test_calculator.html"

    # Run script
    subprocess.run(
        [str(run_script_path), "--no-browser", "--db", str(db_path), "--output", str(html_path)],
        capture_output=True,
        text=True,
        timeout=10,
        check=True
    )

    # Verify HTML file was created and contains expected content
    assert html_path.exists(), f"HTML file not created at {html_path}"

    html_content = html_path.read_text()
    assert "<html" in html_content.lower(), "HTML file doesn't contain HTML markup"
    assert "calculator" in html_content.lower(), "HTML doesn't mention calculator"
    assert "function" in html_content.lower(), "HTML doesn't show function information"

    # Check that it includes call record data
    assert "add" in html_content or "mul" in html_content or "div" in html_content, \
        "HTML doesn't contain calculator function names"


def test_script_help_flag(run_script_path):
    """Test that the script responds to --help flag."""
    result = subprocess.run(
        [str(run_script_path), "--help"],
        capture_output=True,
        text=True,
        timeout=5
    )

    assert result.returncode == 0, "Script failed with --help flag"
    assert "calculator" in result.stdout.lower(), "Help text doesn't mention calculator"
    assert "--no-browser" in result.stdout, "Help text doesn't document --no-browser flag"


def test_script_with_default_paths(run_script_path, temp_output_dir, monkeypatch):
    """Test that the script works with default paths (no arguments)."""
    # Change to temp directory to avoid polluting the repo
    monkeypatch.chdir(temp_output_dir)

    result = subprocess.run(
        [str(run_script_path), "--no-browser"],
        capture_output=True,
        text=True,
        timeout=10
    )

    assert result.returncode == 0, f"Script failed: {result.stderr}"

    # Check that default files were created in current directory
    assert (temp_output_dir / "calculator_example.db").exists(), \
        "Default database not created"
    assert (temp_output_dir / "calculator_example.html").exists(), \
        "Default HTML output not created"
