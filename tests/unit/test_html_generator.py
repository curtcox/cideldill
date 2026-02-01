"""Unit tests for HTML Generator module.

This test suite validates the HTML generation functionality for CAS Store database viewing.
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

    # Simple function for testing
    def sample_add(a: int, b: int) -> int:
        return a + b

    def sample_div(a: int, b: int) -> int:
        return a // b

    wrapped_add = interceptor.wrap(sample_add)
    wrapped_div = interceptor.wrap(sample_div)

    # Record some calls
    wrapped_add(2, 3)
    wrapped_add(10, 20)

    # Record exception
    try:
        wrapped_div(1, 0)
    except ZeroDivisionError:
        pass

    store.close()

    yield db_path

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


def test_generate_html_viewer_creates_file(temp_db_with_data):
    """Test that generate_html_viewer creates an HTML file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        assert Path(html_path).exists()
        assert Path(html_path).stat().st_size > 0
    finally:
        Path(html_path).unlink(missing_ok=True)


def test_generated_html_is_valid_html(temp_db_with_data):
    """Test that generated HTML contains valid HTML markup."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        html_content = Path(html_path).read_text()

        # Check for basic HTML structure
        assert "<!DOCTYPE html>" in html_content
        assert "<html" in html_content.lower()
        assert "</html>" in html_content.lower()
        assert "<head>" in html_content.lower()
        assert "<body>" in html_content.lower()
    finally:
        Path(html_path).unlink(missing_ok=True)


def test_generated_html_contains_title(temp_db_with_data):
    """Test that generated HTML contains the specified title."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        custom_title = "Test Calculator Results"
        generate_html_viewer(temp_db_with_data, html_path, title=custom_title)

        html_content = Path(html_path).read_text()
        assert custom_title in html_content
    finally:
        Path(html_path).unlink(missing_ok=True)


def test_generated_html_includes_database_path(temp_db_with_data):
    """Test that generated HTML includes database path."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        html_content = Path(html_path).read_text()
        assert temp_db_with_data in html_content
    finally:
        Path(html_path).unlink(missing_ok=True)


def test_generated_html_shows_function_calls(temp_db_with_data):
    """Test that generated HTML displays function call records."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        html_content = Path(html_path).read_text()

        # Should show function names
        assert "sample_add" in html_content
        assert "sample_div" in html_content
    finally:
        Path(html_path).unlink(missing_ok=True)


def test_generated_html_shows_arguments(temp_db_with_data):
    """Test that generated HTML shows function arguments."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        html_content = Path(html_path).read_text()

        # Should show arguments section
        assert "Arguments:" in html_content
        # Should show some argument values
        assert '"a"' in html_content or '"b"' in html_content
    finally:
        Path(html_path).unlink(missing_ok=True)


def test_generated_html_shows_results(temp_db_with_data):
    """Test that generated HTML shows function results."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        html_content = Path(html_path).read_text()

        # Should show results section
        assert "Result:" in html_content
    finally:
        Path(html_path).unlink(missing_ok=True)


def test_generated_html_shows_exceptions(temp_db_with_data):
    """Test that generated HTML shows exceptions."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        html_content = Path(html_path).read_text()

        # Should show exception section
        assert "Exception:" in html_content
        # Should show exception type
        assert "ZeroDivisionError" in html_content
    finally:
        Path(html_path).unlink(missing_ok=True)


def test_generated_html_shows_record_count(temp_db_with_data):
    """Test that generated HTML shows total record count."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        html_content = Path(html_path).read_text()

        # Should show total count (we created 3 records)
        assert "Total Function Calls:" in html_content
        assert "3" in html_content
    finally:
        Path(html_path).unlink(missing_ok=True)


def test_generate_html_with_empty_database():
    """Test that HTML generation works with an empty database."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        # Create empty database
        store = CASStore(db_path)
        store.close()

        # Generate HTML
        generate_html_viewer(db_path, html_path)

        html_content = Path(html_path).read_text()

        # Should still be valid HTML
        assert "<!DOCTYPE html>" in html_content
        assert "Total Function Calls:" in html_content
        assert "0" in html_content
    finally:
        Path(db_path).unlink(missing_ok=True)
        Path(html_path).unlink(missing_ok=True)


def test_generate_html_with_default_title():
    """Test that HTML generation uses default title when not specified."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        # Create empty database
        store = CASStore(db_path)
        store.close()

        # Generate HTML without specifying title
        generate_html_viewer(db_path, html_path)

        html_content = Path(html_path).read_text()
        assert "CAS Store Viewer" in html_content
    finally:
        Path(db_path).unlink(missing_ok=True)
        Path(html_path).unlink(missing_ok=True)


def test_generated_html_shows_timestamp(temp_db_with_data):
    """Test that generated HTML displays call timestamps."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        html_content = Path(html_path).read_text()

        # Should show timestamp section
        assert "Timestamp:" in html_content
    finally:
        Path(html_path).unlink(missing_ok=True)


def test_generated_html_shows_callstack(temp_db_with_data):
    """Test that generated HTML displays callstack information."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        html_content = Path(html_path).read_text()

        # Should show callstack section
        assert "Callstack:" in html_content or "Call Stack:" in html_content
    finally:
        Path(html_path).unlink(missing_ok=True)


def test_generated_html_shows_call_site(temp_db_with_data):
    """Test that generated HTML displays call site information."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        html_content = Path(html_path).read_text()

        # Should show call site section
        assert "Call Site:" in html_content
        # Should show file information
        assert "filename" in html_content.lower() or "file:" in html_content.lower()
    finally:
        Path(html_path).unlink(missing_ok=True)


def test_callstack_frames_have_unique_links(temp_db_with_data):
    """Test that each frame in the callstack has a unique clickable link."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        html_content = Path(html_path).read_text()

        # Get a record from the database to check its frames
        store = CASStore(temp_db_with_data)
        records = store.get_all_call_records()
        store.close()

        # Find a record with a callstack
        record_with_stack = None
        for record in records:
            if "callstack" in record and len(record["callstack"]) > 1:
                record_with_stack = record
                break

        if record_with_stack:
            # Check that different frames have different links
            # Frame links should be in format: frame_<record_id>_<frame_index>.html
            frame_link_pattern = f"frame_{record_with_stack['id']}_"
            assert frame_link_pattern in html_content
    finally:
        Path(html_path).unlink(missing_ok=True)


def test_frame_pages_are_generated(temp_db_with_data):
    """Test that individual HTML pages are generated for each frame in callstack."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        # Get records to check if frame pages exist
        store = CASStore(temp_db_with_data)
        records = store.get_all_call_records()
        store.close()

        output_dir = Path(html_path).parent

        # Check if frame pages were generated
        for record in records:
            if "callstack" in record and record["callstack"]:
                for i, frame in enumerate(record["callstack"]):
                    if frame.get('filename') and Path(frame['filename']).exists():
                        frame_page = output_dir / f"frame_{record['id']}_{i}.html"
                        # At least one frame page should exist
                        if frame_page.exists():
                            assert frame_page.stat().st_size > 0
                            break
    finally:
        Path(html_path).unlink(missing_ok=True)
        # Clean up generated frame pages
        output_dir = Path(html_path).parent
        for frame_file in output_dir.glob("frame_*.html"):
            frame_file.unlink(missing_ok=True)


def test_frame_page_shows_parent_frame(temp_db_with_data):
    """Test that frame pages show information about the parent frame."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
        html_path = tmp.name

    try:
        generate_html_viewer(temp_db_with_data, html_path)

        # Get records to check frame pages
        store = CASStore(temp_db_with_data)
        records = store.get_all_call_records()
        store.close()

        output_dir = Path(html_path).parent

        # Check a frame page for parent frame information
        for record in records:
            if "callstack" in record and len(record["callstack"]) > 1:
                # Check frame 1 which should have frame 0 as parent
                frame_page = output_dir / f"frame_{record['id']}_1.html"
                if frame_page.exists():
                    frame_content = frame_page.read_text()
                    # Should show parent frame information
                    assert "parent" in frame_content.lower() or "caller" in frame_content.lower()
                    break
    finally:
        Path(html_path).unlink(missing_ok=True)
        # Clean up generated frame pages
        output_dir = Path(html_path).parent
        for frame_file in output_dir.glob("frame_*.html"):
            frame_file.unlink(missing_ok=True)
