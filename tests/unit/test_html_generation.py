"""Smoke tests for HTML generation and escaping."""

from pathlib import Path

from cideldill_server.cas_store import CASStore
from cideldill_server.html_generator import generate_html_viewer
from cideldill_server.source_viewer import generate_frame_view, generate_source_view


def test_generate_html_viewer_and_escapes_content(tmp_path: Path) -> None:
    db_path = tmp_path / "calls.db"
    source_path = tmp_path / "sample.py"
    source_path.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    store = CASStore(str(db_path))
    call_site = {
        "filename": str(source_path),
        "lineno": 1,
        "function": "add",
        "code_context": "return a < b and c > d <script>alert('x')</script>",
    }
    callstack = [
        {
            "filename": str(source_path),
            "lineno": 1,
            "function": "add",
            "code_context": "return a < b and c > d <script>alert('x')</script>",
        }
    ]
    call_id = store.record_call(
        "add",
        {"a": 1, "b": 2},
        result=3,
        timestamp=123.456,
        callstack=callstack,
        call_site=call_site,
    )
    store.close()

    output_path = tmp_path / "report.html"
    generate_html_viewer(str(db_path), str(output_path))

    assert output_path.exists()
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "timeline.html").exists()
    assert (tmp_path / "sources.html").exists()
    assert (tmp_path / "callstacks.html").exists()
    assert (tmp_path / "breakpoints.html").exists()

    source_html_path = tmp_path / f"source_{call_id}.html"
    frame_html_path = tmp_path / f"frame_{call_id}_0.html"
    assert source_html_path.exists()
    assert frame_html_path.exists()

    source_html = source_html_path.read_text(encoding="utf-8")
    assert "&lt;script&gt;" in source_html
    assert "Timeline View" in (tmp_path / "timeline.html").read_text(encoding="utf-8")


def test_generate_source_and_frame_views_escape(tmp_path: Path) -> None:
    source_file = tmp_path / "demo.py"
    source_file.write_text("print('hi')\n", encoding="utf-8")

    call_record = {
        "id": 1,
        "timestamp": 1.23,
        "args": {"value": "<tag>"},
        "callstack": [
            {
                "filename": str(source_file),
                "lineno": 1,
                "function": "demo",
                "code_context": "print('<tag>')",
            }
        ],
    }

    source_output = tmp_path / "source.html"
    frame_output = tmp_path / "frame.html"

    generate_source_view(
        source_file=str(source_file),
        output_path=str(source_output),
        highlight_line=1,
        call_record=call_record,
        db_path=str(tmp_path / "db.sqlite"),
    )
    generate_frame_view(
        source_file=str(source_file),
        output_path=str(frame_output),
        highlight_line=1,
        call_record=call_record,
        frame_index=0,
        db_path=str(tmp_path / "db.sqlite"),
    )

    assert "&lt;tag&gt;" in source_output.read_text(encoding="utf-8")
    assert "&lt;tag&gt;" in frame_output.read_text(encoding="utf-8")
