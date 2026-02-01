"""Unit tests for Source Viewer module.

This test suite validates the source code viewing functionality with syntax highlighting
and navigation capabilities.
"""

import tempfile
from pathlib import Path

import pytest

from cideldill import CASStore, Interceptor


@pytest.fixture
def temp_db_with_multiple_calls():
    """Create a temporary database with multiple call records for navigation testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    # Create and populate database
    store = CASStore(db_path)
    interceptor = Interceptor(store)

    # Create test functions
    def add(a: int, b: int) -> int:
        return a + b

    def multiply(a: int, b: int) -> int:
        return a * b

    wrapped_add = interceptor.wrap(add)
    wrapped_multiply = interceptor.wrap(multiply)

    # Record multiple calls to test navigation
    wrapped_add(1, 2)  # Call 1
    wrapped_multiply(3, 4)  # Call 2
    wrapped_add(5, 6)  # Call 3
    wrapped_multiply(7, 8)  # Call 4
    wrapped_add(9, 10)  # Call 5

    store.close()

    yield db_path

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def sample_python_file():
    """Create a temporary Python file for source viewing."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write("""def example_function(x, y):
    '''Example function for testing.'''
    result = x + y
    return result

def another_function(a, b):
    '''Another example function.'''
    value = a * b
    return value
""")
        file_path = tmp.name

    yield file_path

    # Cleanup
    Path(file_path).unlink(missing_ok=True)


class TestSourceViewerGeneration:
    """Tests for generating source code viewer HTML pages."""

    def test_generate_source_view_creates_html(self, sample_python_file):
        """Test that source viewer generates an HTML file."""
        from cideldill.source_viewer import generate_source_view

        output_path = tempfile.mktemp(suffix=".html")

        try:
            generate_source_view(
                source_file=sample_python_file,
                output_path=output_path,
                highlight_line=3,
            )

            assert Path(output_path).exists()
            assert Path(output_path).stat().st_size > 0
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_generated_source_view_is_valid_html(self, sample_python_file):
        """Test that generated source view contains valid HTML."""
        from cideldill.source_viewer import generate_source_view

        output_path = tempfile.mktemp(suffix=".html")

        try:
            generate_source_view(
                source_file=sample_python_file,
                output_path=output_path,
                highlight_line=3,
            )

            html_content = Path(output_path).read_text()

            # Check for basic HTML structure
            assert "<!DOCTYPE html>" in html_content
            assert "<html" in html_content.lower()
            assert "</html>" in html_content.lower()
            assert "<head>" in html_content.lower()
            assert "<body>" in html_content.lower()
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_generated_source_view_contains_syntax_highlighting(self, sample_python_file):
        """Test that source view includes syntax highlighting."""
        from cideldill.source_viewer import generate_source_view

        output_path = tempfile.mktemp(suffix=".html")

        try:
            generate_source_view(
                source_file=sample_python_file,
                output_path=output_path,
                highlight_line=3,
            )

            html_content = Path(output_path).read_text()

            # Should contain Python code
            assert "example_function" in html_content
            assert "another_function" in html_content

            # Should contain Pygments-style syntax highlighting
            # (either inline styles or CSS classes)
            assert ("style=" in html_content or "class=" in html_content)
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_generated_source_view_highlights_specific_line(self, sample_python_file):
        """Test that source view highlights the specified line."""
        from cideldill.source_viewer import generate_source_view

        output_path = tempfile.mktemp(suffix=".html")

        try:
            highlight_lineno = 3
            generate_source_view(
                source_file=sample_python_file,
                output_path=output_path,
                highlight_line=highlight_lineno,
            )

            html_content = Path(output_path).read_text()

            # Should have highlighting marker or style for the line
            # The exact format depends on implementation, but should be noticeable
            assert "highlight" in html_content.lower() or "background" in html_content
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_source_view_with_call_context(self, sample_python_file, temp_db_with_multiple_calls):
        """Test that source view can include call context information."""
        from cideldill.source_viewer import generate_source_view

        output_path = tempfile.mktemp(suffix=".html")
        store = CASStore(temp_db_with_multiple_calls)

        try:
            call_record = store.get_call_record(1)
            assert call_record is not None

            generate_source_view(
                source_file=sample_python_file,
                output_path=output_path,
                highlight_line=3,
                call_record=call_record,
            )

            html_content = Path(output_path).read_text()

            # Should show call information
            assert "timestamp" in html_content.lower() or "time" in html_content.lower()
            assert "parameters" in html_content.lower() or "arguments" in html_content.lower()
        finally:
            store.close()
            Path(output_path).unlink(missing_ok=True)

    def test_source_view_with_callstack(self, sample_python_file, temp_db_with_multiple_calls):
        """Test that source view displays callstack information."""
        from cideldill.source_viewer import generate_source_view

        output_path = tempfile.mktemp(suffix=".html")
        store = CASStore(temp_db_with_multiple_calls)

        try:
            call_record = store.get_call_record(1)
            assert call_record is not None

            generate_source_view(
                source_file=sample_python_file,
                output_path=output_path,
                highlight_line=3,
                call_record=call_record,
            )

            html_content = Path(output_path).read_text()

            # Should show callstack
            assert "callstack" in html_content.lower() or "call stack" in html_content.lower()
        finally:
            store.close()
            Path(output_path).unlink(missing_ok=True)


class TestNavigationLinks:
    """Tests for navigation link generation in source viewer."""

    def test_source_view_has_navigation_section(self, sample_python_file, temp_db_with_multiple_calls):
        """Test that source view includes a navigation section."""
        from cideldill.source_viewer import generate_source_view

        output_path = tempfile.mktemp(suffix=".html")
        store = CASStore(temp_db_with_multiple_calls)

        try:
            call_record = store.get_call_record(2)  # Middle record
            assert call_record is not None

            generate_source_view(
                source_file=sample_python_file,
                output_path=output_path,
                highlight_line=3,
                call_record=call_record,
                db_path=temp_db_with_multiple_calls,
            )

            html_content = Path(output_path).read_text()

            # Should have navigation section
            assert "navigation" in html_content.lower() or "previous" in html_content.lower()
        finally:
            store.close()
            Path(output_path).unlink(missing_ok=True)

    def test_source_view_has_next_previous_timestamp_links(
        self, sample_python_file, temp_db_with_multiple_calls
    ):
        """Test that source view includes next/previous timestamp links."""
        from cideldill.source_viewer import generate_source_view

        output_path = tempfile.mktemp(suffix=".html")
        store = CASStore(temp_db_with_multiple_calls)

        try:
            call_record = store.get_call_record(3)  # Middle record
            assert call_record is not None

            generate_source_view(
                source_file=sample_python_file,
                output_path=output_path,
                highlight_line=3,
                call_record=call_record,
                db_path=temp_db_with_multiple_calls,
            )

            html_content = Path(output_path).read_text()

            # Should have links to next/previous by timestamp
            assert ("next" in html_content.lower() and "previous" in html_content.lower())
        finally:
            store.close()
            Path(output_path).unlink(missing_ok=True)

    def test_source_view_has_same_function_navigation_links(
        self, sample_python_file, temp_db_with_multiple_calls
    ):
        """Test that source view includes links to next/previous calls of same function."""
        from cideldill.source_viewer import generate_source_view

        output_path = tempfile.mktemp(suffix=".html")
        store = CASStore(temp_db_with_multiple_calls)

        try:
            call_record = store.get_call_record(3)  # Second call to 'add'
            assert call_record is not None

            generate_source_view(
                source_file=sample_python_file,
                output_path=output_path,
                highlight_line=3,
                call_record=call_record,
                db_path=temp_db_with_multiple_calls,
            )

            html_content = Path(output_path).read_text()

            # Should have links for same function navigation
            assert "same function" in html_content.lower() or call_record["function_name"] in html_content
        finally:
            store.close()
            Path(output_path).unlink(missing_ok=True)


class TestCASStoreNavigationQueries:
    """Tests for CASStore navigation query methods."""

    def test_get_next_call_by_timestamp(self, temp_db_with_multiple_calls):
        """Test getting the next call record by timestamp."""
        store = CASStore(temp_db_with_multiple_calls)

        try:
            current_record = store.get_call_record(2)
            assert current_record is not None

            next_record = store.get_next_call_by_timestamp(current_record["id"])
            assert next_record is not None
            assert next_record["id"] == 3
            assert next_record["timestamp"] > current_record["timestamp"]
        finally:
            store.close()

    def test_get_previous_call_by_timestamp(self, temp_db_with_multiple_calls):
        """Test getting the previous call record by timestamp."""
        store = CASStore(temp_db_with_multiple_calls)

        try:
            current_record = store.get_call_record(3)
            assert current_record is not None

            prev_record = store.get_previous_call_by_timestamp(current_record["id"])
            assert prev_record is not None
            assert prev_record["id"] == 2
            assert prev_record["timestamp"] < current_record["timestamp"]
        finally:
            store.close()

    def test_get_next_call_by_timestamp_returns_none_at_end(self, temp_db_with_multiple_calls):
        """Test that get_next_call_by_timestamp returns None for the last record."""
        store = CASStore(temp_db_with_multiple_calls)

        try:
            last_record = store.get_call_record(5)
            assert last_record is not None

            next_record = store.get_next_call_by_timestamp(last_record["id"])
            assert next_record is None
        finally:
            store.close()

    def test_get_previous_call_by_timestamp_returns_none_at_start(self, temp_db_with_multiple_calls):
        """Test that get_previous_call_by_timestamp returns None for the first record."""
        store = CASStore(temp_db_with_multiple_calls)

        try:
            first_record = store.get_call_record(1)
            assert first_record is not None

            prev_record = store.get_previous_call_by_timestamp(first_record["id"])
            assert prev_record is None
        finally:
            store.close()

    def test_get_next_call_of_same_function(self, temp_db_with_multiple_calls):
        """Test getting the next call of the same function."""
        store = CASStore(temp_db_with_multiple_calls)

        try:
            # Get first 'add' call (id=1)
            first_add = store.get_call_record(1)
            assert first_add is not None
            assert first_add["function_name"] == "add"

            # Should get second 'add' call (id=3)
            next_add = store.get_next_call_of_same_function(first_add["id"])
            assert next_add is not None
            assert next_add["id"] == 3
            assert next_add["function_name"] == "add"
        finally:
            store.close()

    def test_get_previous_call_of_same_function(self, temp_db_with_multiple_calls):
        """Test getting the previous call of the same function."""
        store = CASStore(temp_db_with_multiple_calls)

        try:
            # Get third 'add' call (id=5)
            third_add = store.get_call_record(5)
            assert third_add is not None
            assert third_add["function_name"] == "add"

            # Should get second 'add' call (id=3)
            prev_add = store.get_previous_call_of_same_function(third_add["id"])
            assert prev_add is not None
            assert prev_add["id"] == 3
            assert prev_add["function_name"] == "add"
        finally:
            store.close()

    def test_get_next_call_of_same_function_returns_none_at_end(self, temp_db_with_multiple_calls):
        """Test that next call of same function returns None at the end."""
        store = CASStore(temp_db_with_multiple_calls)

        try:
            # Get last 'add' call (id=5)
            last_add = store.get_call_record(5)
            assert last_add is not None

            next_add = store.get_next_call_of_same_function(last_add["id"])
            assert next_add is None
        finally:
            store.close()

    def test_get_previous_call_of_same_function_returns_none_at_start(
        self, temp_db_with_multiple_calls
    ):
        """Test that previous call of same function returns None at the start."""
        store = CASStore(temp_db_with_multiple_calls)

        try:
            # Get first 'add' call (id=1)
            first_add = store.get_call_record(1)
            assert first_add is not None

            prev_add = store.get_previous_call_of_same_function(first_add["id"])
            assert prev_add is None
        finally:
            store.close()


class TestHTMLGeneratorSourceLinks:
    """Tests for adding source navigation links to HTML generator output."""

    def test_html_generator_includes_source_links(self, temp_db_with_multiple_calls):
        """Test that HTML generator includes links to source viewer."""
        from cideldill.html_generator import generate_html_viewer

        output_path = tempfile.mktemp(suffix=".html")

        try:
            generate_html_viewer(
                db_path=temp_db_with_multiple_calls,
                output_path=output_path,
            )

            html_content = Path(output_path).read_text()

            # Should have links to source viewer
            assert "source" in html_content.lower() or "view code" in html_content.lower()
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_html_generator_call_site_has_source_link(self, temp_db_with_multiple_calls):
        """Test that call site information includes link to source viewer."""
        from cideldill.html_generator import generate_html_viewer

        output_path = tempfile.mktemp(suffix=".html")

        try:
            generate_html_viewer(
                db_path=temp_db_with_multiple_calls,
                output_path=output_path,
            )

            html_content = Path(output_path).read_text()

            # Call site should be clickable
            assert "Call Site:" in html_content
            # Should have a link (href attribute)
            assert 'href=' in html_content.lower()
        finally:
            Path(output_path).unlink(missing_ok=True)

    def test_html_generator_callstack_frames_have_source_links(self, temp_db_with_multiple_calls):
        """Test that callstack frames include links to source viewer."""
        from cideldill.html_generator import generate_html_viewer

        output_path = tempfile.mktemp(suffix=".html")

        try:
            generate_html_viewer(
                db_path=temp_db_with_multiple_calls,
                output_path=output_path,
            )

            html_content = Path(output_path).read_text()

            # Callstack should be present
            assert "Call Stack:" in html_content
            # Should have links in callstack frames
            assert 'href=' in html_content.lower()
        finally:
            Path(output_path).unlink(missing_ok=True)
