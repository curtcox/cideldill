"""Unit tests for Web UI Navigation features.

This test suite validates the web UI navigation functionality including
home page, timeline view, source files list, call stacks list, and breakpoints.
"""

import tempfile
from pathlib import Path

import pytest

from cideldill import CASStore, Interceptor
from cideldill.html_generator import generate_html_viewer


@pytest.fixture
def temp_db_with_data():
    """Create a temporary database with sample call records."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    # Create and populate database
    store = CASStore(db_path)
    interceptor = Interceptor(store)

    # Simple functions for testing
    def sample_add(a: int, b: int) -> int:
        return a + b

    def sample_mul(a: int, b: int) -> int:
        return a * b

    wrapped_add = interceptor.wrap(sample_add)
    wrapped_mul = interceptor.wrap(sample_mul)

    # Record some calls
    wrapped_add(2, 3)
    wrapped_mul(4, 5)
    wrapped_add(10, 20)

    store.close()

    yield db_path

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


def test_generated_html_has_home_link(temp_db_with_data):
    """Test that all generated pages have a link to home."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        html_content = Path(html_path).read_text()

        # Should have a link to home page (index.html)
        assert 'href="index.html"' in html_content or 'href="home.html"' in html_content
    finally:
        Path(html_path).unlink(missing_ok=True)


def test_home_page_is_generated(temp_db_with_data):
    """Test that a home/index page is generated."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        output_dir = Path(html_path).parent
        # Check if home page exists (either index.html or home.html)
        home_page = output_dir / "index.html"
        if not home_page.exists():
            home_page = output_dir / "home.html"

        assert home_page.exists()
        assert home_page.stat().st_size > 0
    finally:
        Path(html_path).unlink(missing_ok=True)
        # Cleanup home page
        for home_file in [output_dir / "index.html", output_dir / "home.html"]:
            home_file.unlink(missing_ok=True)


def test_home_page_has_navigation_links(temp_db_with_data):
    """Test that home page has links to all main views."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        output_dir = Path(html_path).parent
        home_page = output_dir / "index.html"

        if home_page.exists():
            home_content = home_page.read_text()

            # Should have links to main views
            assert "timeline" in home_content.lower() or "calls" in home_content.lower()
            assert "source" in home_content.lower() or "files" in home_content.lower()
            assert "stack" in home_content.lower() or "callstack" in home_content.lower()
            assert "breakpoint" in home_content.lower()
    finally:
        Path(html_path).unlink(missing_ok=True)
        # Cleanup
        for home_file in [output_dir / "index.html", output_dir / "home.html"]:
            home_file.unlink(missing_ok=True)


def test_timeline_page_is_generated(temp_db_with_data):
    """Test that a timeline/graph page is generated."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        output_dir = Path(html_path).parent
        timeline_page = output_dir / "timeline.html"

        assert timeline_page.exists()
        assert timeline_page.stat().st_size > 0
    finally:
        Path(html_path).unlink(missing_ok=True)
        # Cleanup
        (output_dir / "timeline.html").unlink(missing_ok=True)


def test_timeline_page_shows_all_calls(temp_db_with_data):
    """Test that timeline page displays all function calls."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        output_dir = Path(html_path).parent
        timeline_page = output_dir / "timeline.html"

        if timeline_page.exists():
            timeline_content = timeline_page.read_text()

            # Should show function names
            assert "sample_add" in timeline_content
            assert "sample_mul" in timeline_content

            # Should have links to individual call records (format: source_<id>.html)
            assert 'href="source_' in timeline_content
    finally:
        Path(html_path).unlink(missing_ok=True)
        # Cleanup
        (output_dir / "timeline.html").unlink(missing_ok=True)


def test_source_files_page_is_generated(temp_db_with_data):
    """Test that a source files list page is generated."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        output_dir = Path(html_path).parent
        sources_page = output_dir / "sources.html"

        assert sources_page.exists()
        assert sources_page.stat().st_size > 0
    finally:
        Path(html_path).unlink(missing_ok=True)
        # Cleanup
        (output_dir / "sources.html").unlink(missing_ok=True)


def test_source_files_page_lists_all_files(temp_db_with_data):
    """Test that source files page lists all unique source files."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        output_dir = Path(html_path).parent
        sources_page = output_dir / "sources.html"

        if sources_page.exists():
            sources_content = sources_page.read_text()

            # Should show source file information
            assert "test_web_ui_navigation.py" in sources_content or ".py" in sources_content

            # Should have links to view source files
            assert "<a" in sources_content
    finally:
        Path(html_path).unlink(missing_ok=True)
        # Cleanup
        (output_dir / "sources.html").unlink(missing_ok=True)


def test_call_stacks_page_is_generated(temp_db_with_data):
    """Test that a call stacks list page is generated."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        output_dir = Path(html_path).parent
        stacks_page = output_dir / "callstacks.html"

        assert stacks_page.exists()
        assert stacks_page.stat().st_size > 0
    finally:
        Path(html_path).unlink(missing_ok=True)
        # Cleanup
        (output_dir / "callstacks.html").unlink(missing_ok=True)


def test_call_stacks_page_lists_all_stacks(temp_db_with_data):
    """Test that call stacks page lists all call stacks."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        output_dir = Path(html_path).parent
        stacks_page = output_dir / "callstacks.html"

        if stacks_page.exists():
            stacks_content = stacks_page.read_text()

            # Should show callstack information
            assert "function" in stacks_content.lower() or "frame" in stacks_content.lower()

            # Should have links to view call stacks
            assert "<a" in stacks_content
    finally:
        Path(html_path).unlink(missing_ok=True)
        # Cleanup
        (output_dir / "callstacks.html").unlink(missing_ok=True)


def test_breakpoints_page_is_generated(temp_db_with_data):
    """Test that a breakpoints management page is generated."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        output_dir = Path(html_path).parent
        breakpoints_page = output_dir / "breakpoints.html"

        assert breakpoints_page.exists()
        assert breakpoints_page.stat().st_size > 0
    finally:
        Path(html_path).unlink(missing_ok=True)
        # Cleanup
        (output_dir / "breakpoints.html").unlink(missing_ok=True)


def test_breakpoints_page_shows_functions(temp_db_with_data):
    """Test that breakpoints page shows available functions."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        output_dir = Path(html_path).parent
        breakpoints_page = output_dir / "breakpoints.html"

        if breakpoints_page.exists():
            breakpoints_content = breakpoints_page.read_text()

            # Should show function names that can have breakpoints
            assert "sample_add" in breakpoints_content or "function" in breakpoints_content.lower()

            # Should have UI elements for setting/unsetting breakpoints
            assert "breakpoint" in breakpoints_content.lower()
    finally:
        Path(html_path).unlink(missing_ok=True)
        # Cleanup
        (output_dir / "breakpoints.html").unlink(missing_ok=True)


def test_all_pages_have_navigation_header(temp_db_with_data):
    """Test that all generated pages have a common navigation header."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        output_dir = Path(html_path).parent

        # Check main pages for navigation
        pages_to_check = [
            html_path,
            output_dir / "index.html",
            output_dir / "timeline.html",
            output_dir / "sources.html",
            output_dir / "callstacks.html",
            output_dir / "breakpoints.html",
        ]

        for page in pages_to_check:
            if Path(page).exists():
                content = Path(page).read_text()
                # Should have navigation elements
                assert "<nav" in content.lower() or "navigation" in content.lower()
                # Should have link to home
                assert "home" in content.lower() or "index" in content.lower()
    finally:
        Path(html_path).unlink(missing_ok=True)
        # Cleanup all generated pages
        for page in ["index.html", "timeline.html", "sources.html", "callstacks.html",
                     "breakpoints.html"]:
            (output_dir / page).unlink(missing_ok=True)
