"""HTML Generator for CAS Store Database Viewer.

This module provides utilities to generate HTML views of CAS Store database content,
particularly for visualizing function call records from the calculator examples.
"""

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .port_discovery import get_discovery_file_path, read_port_file

TEMPLATES_DIR = Path(__file__).with_name("templates")


def _escape_text(value: object) -> str:
    return html.escape(str(value), quote=True)


def _render_template(name: str, replacements: dict[str, str]) -> str:
    template_path = TEMPLATES_DIR / name
    template = template_path.read_text(encoding="utf-8")
    for key, value in replacements.items():
        template = template.replace(f"__{key}__", value)
    return template


def generate_html_viewer(db_path: str, output_path: str, title: str = "CAS Store Viewer") -> None:
    """Generate an HTML viewer for a CAS Store database.

    Args:
        db_path: Path to the SQLite database file.
        output_path: Path where the HTML file should be written.
        title: Title for the HTML page.
    """
    # Read data from database using CASStore
    from .cas_store import CASStore

    store = CASStore(db_path)
    records = store.get_all_call_records()
    store.close()

    # Generate HTML
    html_content = _generate_html(title, db_path, records)

    # Write to file
    Path(output_path).write_text(html_content)

    # Generate source viewer pages for each record with call site information
    _generate_source_viewer_pages(db_path, output_path)

    # Generate additional web UI pages
    _generate_web_ui_pages(db_path, output_path, records)


def _generate_html(title: str, db_path: str, records: list[dict[str, Any]]) -> str:
    """Generate the HTML content.

    Args:
        title: Page title.
        db_path: Path to the database.
        records: List of call records.

    Returns:
        Complete HTML page as a string.
    """
    records_html = ""
    for record in records:
        records_html += _format_record(record, db_path)

    nav_header = _generate_navigation_header("")

    return _render_template(
        "viewer.html",
        {
            "TITLE": _escape_text(title),
            "NAV_HEADER": nav_header,
            "DB_PATH": _escape_text(db_path),
            "TOTAL_CALLS": _escape_text(len(records)),
            "RECORDS_HTML": records_html,
        },
    )


def _format_record(record: dict[str, Any], db_path: str = "") -> str:
    """Format a single call record as HTML.

    Args:
        record: Call record dictionary.
        db_path: Path to the database for generating source links.

    Returns:
        HTML string for the record.
    """
    html = f"""
    <div class="record">
        <div class="record-header">
            <span class="function-name">{_escape_text(record['function_name'])}()</span>
            <span class="record-id">Record #{_escape_text(record['id'])}</span>
        </div>
"""

    # Timestamp
    if "timestamp" in record:
        from datetime import datetime
        timestamp = record["timestamp"]
        # Format timestamp as human-readable date
        dt = datetime.fromtimestamp(timestamp)
        timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]  # Include milliseconds
        html += f"""
        <div class="section">
            <div class="section-title">Timestamp:</div>
            <div class="timestamp">{_escape_text(timestamp_str)} (Unix: {_escape_text(timestamp)})</div>
        </div>
"""

    # Call Site
    if "call_site" in record:
        call_site = record["call_site"]
        source_link = ""
        if db_path and "id" in record:
            link_url = f"source_{record['id']}.html"
            link_style = "color: #2196F3; text-decoration: none; font-weight: bold;"
            source_link = (
                f' <a href="{_escape_text(link_url)}" style="{link_style}">[View Source]</a>'
            )
        html += f"""
        <div class="section">
            <div class="section-title">Call Site:{source_link}</div>
            <div class="code-block">
                <strong>File:</strong> {_escape_text(call_site.get('filename', 'N/A'))}<br>
                <strong>Line:</strong> {_escape_text(call_site.get('lineno', 'N/A'))}<br>
                <strong>Function:</strong> {_escape_text(call_site.get('function', 'N/A'))}<br>
"""
        if call_site.get('code_context'):
            code_ctx = call_site['code_context']
            html += f"                <strong>Code:</strong> <code>{_escape_text(code_ctx)}</code><br>\n"
        html += """            </div>
        </div>
"""

    # Arguments
    if "args" in record:
        args_str = json.dumps(record["args"], indent=2)
        html += f"""
        <div class="section">
            <div class="section-title">Arguments:</div>
            <div class="code-block">{_escape_text(args_str)}</div>
        </div>
"""

    # Result
    if "result" in record:
        result_str = json.dumps(record["result"], indent=2)
        html += f"""
        <div class="section">
            <div class="section-title result">Result:</div>
            <div class="code-block result">{_escape_text(result_str)}</div>
        </div>
"""

    # Exception
    if "exception" in record:
        exception_str = json.dumps(record["exception"], indent=2)
        html += f"""
        <div class="section">
            <div class="section-title exception">Exception:</div>
            <div class="code-block exception">{_escape_text(exception_str)}</div>
        </div>
"""

    # Callstack
    if "callstack" in record and record["callstack"]:
        html += """
        <div class="section">
            <div class="section-title">Call Stack:</div>
            <div class="code-block">
"""
        for i, frame in enumerate(record["callstack"]):
            frame_style = (
                "margin-bottom: 10px; padding: 5px; "
                "background-color: #f9f9f9; border-left: 3px solid #ddd;"
            )
            # Add source link for each frame with unique URL
            frame_link = ""
            if db_path and frame.get('filename') and frame.get('lineno'):
                link_url = f"frame_{record['id']}_{i}.html"
                link_style = "color: #2196F3; text-decoration: none; font-size: 0.9em;"
                frame_link = (
                    f' <a href="{_escape_text(link_url)}" style="{link_style}">[view]</a>'
                )
            html += f"""                <div style="{frame_style}">
                    <strong>Frame {i}:</strong> {_escape_text(frame.get('function', 'N/A'))}{frame_link}<br>
                    <strong>File:</strong> {_escape_text(frame.get('filename', 'N/A'))}<br>
                    <strong>Line:</strong> {_escape_text(frame.get('lineno', 'N/A'))}<br>
"""
            if frame.get('code_context'):
                code_ctx = frame['code_context']
                html += f"                    <strong>Code:</strong> <code>{_escape_text(code_ctx)}</code><br>\n"
            html += "                </div>\n"
        html += """            </div>
        </div>
"""

    html += """
    </div>
"""

    return html


def _generate_source_viewer_pages(db_path: str, main_output_path: str) -> None:
    """Generate source viewer pages for all call records and their frames.

    Args:
        db_path: Path to the database.
        main_output_path: Path to the main HTML output file (used for determining output directory).
    """
    from .cas_store import CASStore
    from .source_viewer import generate_frame_view, generate_source_view

    store = CASStore(db_path)
    records = store.get_all_call_records()
    store.close()

    output_dir = Path(main_output_path).parent

    for record in records:
        call_site = record.get("call_site")
        if not call_site:
            continue

        filename = call_site.get("filename")
        lineno = call_site.get("lineno")

        if not filename or not Path(filename).exists():
            continue

        # Generate source viewer for this call
        source_output = output_dir / f"source_{record['id']}.html"
        try:
            generate_source_view(
                source_file=filename,
                output_path=str(source_output),
                highlight_line=lineno,
                call_record=record,
                db_path=db_path,
            )
        except OSError:
            # Skip source generation if file cannot be read or written
            # This is expected for some cases like temporary files or stdin
            pass
        except Exception as e:
            # Log unexpected errors but continue processing other records
            # This prevents a single problematic file from breaking the entire report
            import sys
            print(f"Warning: Failed to generate source view for record {record['id']}: {e}",
                  file=sys.stderr)

        # Generate individual pages for each frame in the callstack
        callstack = record.get("callstack", [])
        for frame_index, frame in enumerate(callstack):
            frame_filename = frame.get("filename")
            frame_lineno = frame.get("lineno")

            if not frame_filename or not Path(frame_filename).exists():
                continue

            frame_output = output_dir / f"frame_{record['id']}_{frame_index}.html"
            try:
                generate_frame_view(
                    source_file=frame_filename,
                    output_path=str(frame_output),
                    highlight_line=frame_lineno,
                    call_record=record,
                    frame_index=frame_index,
                    db_path=db_path,
                )
            except OSError:
                # Skip frame generation if file cannot be read or written
                pass
            except Exception as e:
                # Log unexpected errors but continue processing other frames
                import sys
                print(f"Warning: Failed to generate frame view for record {record['id']}, "
                      f"frame {frame_index}: {e}", file=sys.stderr)


def _generate_navigation_header(current_page: str = "") -> str:
    """Generate a common navigation header for all pages.

    Args:
        current_page: Name of the current page (for highlighting).

    Returns:
        HTML string for the navigation header.
    """
    pages = [
        ("index.html", "Home"),
        ("timeline.html", "Timeline"),
        ("sources.html", "Source Files"),
        ("callstacks.html", "Call Stacks"),
        ("breakpoints.html", "Breakpoints"),
    ]

    nav_links = []
    for page, label in pages:
        if page == current_page:
            nav_links.append(f'<span style="font-weight: bold;">{label}</span>')
        else:
            nav_links.append(f'<a href="{page}" class="nav-link">{label}</a>')

    nav_html = f"""
    <nav style="background-color: #2196F3; padding: 15px; margin: -20px -20px 20px -20px;
                border-radius: 0;">
        <div style="max-width: 1200px; margin: 0 auto; display: flex; gap: 20px;
                    flex-wrap: wrap; align-items: center;">
            <h2 style="margin: 0; color: white; font-size: 1.2em;">CID el Dill Viewer</h2>
            <div style="display: flex; gap: 15px; flex-wrap: wrap; margin-left: auto;">
                {' | '.join(nav_links)}
            </div>
        </div>
    </nav>
    <style>
        .nav-link {{
            color: white;
            text-decoration: none;
            padding: 8px 16px;
            background-color: rgba(255, 255, 255, 0.1);
            border-radius: 4px;
            transition: background-color 0.2s;
        }}
        .nav-link:hover {{
            background-color: rgba(255, 255, 255, 0.2);
        }}
    </style>
"""
    return nav_html


def _generate_web_ui_pages(
    db_path: str, main_output_path: str, records: list[dict[str, Any]]
) -> None:
    """Generate additional web UI pages for navigation and viewing.

    Args:
        db_path: Path to the database.
        main_output_path: Path to the main HTML output file.
        records: List of all call records.
    """
    output_dir = Path(main_output_path).parent

    # Generate home/index page
    _generate_home_page(output_dir, db_path, records)

    # Generate timeline page
    _generate_timeline_page(output_dir, db_path, records)

    # Generate source files list page
    _generate_sources_page(output_dir, db_path, records)

    # Generate call stacks list page
    _generate_callstacks_page(output_dir, db_path, records)

    # Generate breakpoints management page
    _generate_breakpoints_page(output_dir, db_path, records)


def _generate_home_page(output_dir: Path, db_path: str, records: list[dict[str, Any]]) -> None:
    """Generate the home/index page.

    Args:
        output_dir: Directory for output files.
        db_path: Path to the database.
        records: List of all call records.
    """
    nav_header = _generate_navigation_header("index.html")

    # Get statistics
    total_calls = len(records)
    unique_functions = len({r.get('function_name', '') for r in records})
    unique_files = len({
        r.get('call_site', {}).get('filename', '')
        for r in records
        if r.get('call_site', {}).get('filename')
    })

    html = _render_template(
        "home.html",
        {
            "NAV_HEADER": nav_header,
            "TOTAL_CALLS": _escape_text(total_calls),
            "UNIQUE_FUNCTIONS": _escape_text(unique_functions),
            "UNIQUE_FILES": _escape_text(unique_files),
            "DB_PATH": _escape_text(db_path),
        },
    )

    index_path = output_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")


def _generate_timeline_page(output_dir: Path, db_path: str, records: list[dict[str, Any]]) -> None:
    """Generate the timeline/graph page.

    Args:
        output_dir: Directory for output files.
        db_path: Path to the database.
        records: List of all call records.
    """
    nav_header = _generate_navigation_header("timeline.html")

    # Sort records by timestamp
    sorted_records = sorted(records, key=lambda r: r.get("timestamp", 0))

    timeline_html = ""
    for record in sorted_records:
        timestamp = record.get("timestamp", 0)
        dt = datetime.fromtimestamp(timestamp)
        timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        # Check if the record has an exception
        has_exception = "exception" in record and record["exception"] is not None
        result_str = "Exception" if has_exception else str(record.get("result", "N/A"))
        link_url = f"source_{record['id']}.html"

        timeline_html += f"""
        <div class="timeline-item">
            <div class="timeline-time">{_escape_text(timestamp_str)}</div>
            <div class="timeline-content">
                <div class="timeline-function">{_escape_text(record.get('function_name', 'Unknown'))}()</div>
                <div class="timeline-result">Result: {_escape_text(result_str)}</div>
                <a href="{_escape_text(link_url)}" class="timeline-link">View Details →</a>
            </div>
        </div>
"""
    html = _render_template(
        "timeline.html",
        {
            "NAV_HEADER": nav_header,
            "TIMELINE_HTML": timeline_html,
        },
    )

    timeline_path = output_dir / "timeline.html"
    timeline_path.write_text(html, encoding="utf-8")


def _generate_sources_page(output_dir: Path, db_path: str, records: list[dict[str, Any]]) -> None:
    """Generate the source files list page.

    Args:
        output_dir: Directory for output files.
        db_path: Path to the database.
        records: List of all call records.
    """
    nav_header = _generate_navigation_header("sources.html")

    # Group records by source file
    files_dict: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        filename = record.get("call_site", {}).get("filename")
        if filename:
            if filename not in files_dict:
                files_dict[filename] = []
            files_dict[filename].append(record)

    files_html = ""
    for filename, file_records in sorted(files_dict.items()):
        files_html += f"""
        <div class="file-card">
            <div class="file-name">{_escape_text(filename)}</div>
            <div class="file-stats">{_escape_text(len(file_records))} call(s)</div>
            <div class="file-calls">
"""
        for record in file_records[:5]:  # Show first 5 calls
            link_url = f"source_{record['id']}.html"
            files_html += f"""
                <a href="{_escape_text(link_url)}" class="call-link">
                    {_escape_text(record.get('function_name', 'Unknown'))}()
                    [Line {_escape_text(record.get('call_site', {}).get('lineno', '?'))}]
                </a>
"""
        if len(file_records) > 5:
            files_html += (
                f'<div class="more">... and {_escape_text(len(file_records) - 5)} more</div>'
            )

        files_html += """
            </div>
        </div>
"""

    html = _render_template(
        "sources.html",
        {
            "NAV_HEADER": nav_header,
            "FILES_HTML": files_html if files_html else "<p>No source files found.</p>",
        },
    )

    sources_path = output_dir / "sources.html"
    sources_path.write_text(html, encoding="utf-8")


def _generate_callstacks_page(
    output_dir: Path, db_path: str, records: list[dict[str, Any]]
) -> None:
    """Generate the call stacks list page.

    Args:
        output_dir: Directory for output files.
        db_path: Path to the database.
        records: List of all call records.
    """
    nav_header = _generate_navigation_header("callstacks.html")

    stacks_html = ""
    for record in records:
        if not record.get("callstack"):
            continue

        callstack = record.get("callstack", [])
        link_url = f"source_{record['id']}.html"

        stacks_html += f"""
        <div class="stack-card">
            <div class="stack-header">
                <span class="stack-function">{_escape_text(record.get('function_name', 'Unknown'))}()</span>
                <span class="stack-depth">Depth: {_escape_text(len(callstack))}</span>
            </div>
            <div class="stack-frames">
"""
        for i, frame in enumerate(callstack[:5]):  # Show first 5 frames
            stacks_html += f"""
                <div class="stack-frame">
                    Frame {i}: {_escape_text(frame.get('function', 'Unknown'))}
                    [{_escape_text(frame.get('filename', 'Unknown'))}:{_escape_text(frame.get('lineno', '?'))}]
                </div>
"""
        if len(callstack) > 5:
            stacks_html += (
                f"<div class='more'>... and {_escape_text(len(callstack) - 5)} more frames</div>"
            )

        stacks_html += f"""
            </div>
            <a href="{_escape_text(link_url)}" class="view-link">View Full Stack →</a>
        </div>
"""
    html = _render_template(
        "callstacks.html",
        {
            "NAV_HEADER": nav_header,
            "STACKS_HTML": stacks_html if stacks_html else "<p>No call stacks found.</p>",
        },
    )

    stacks_path = output_dir / "callstacks.html"
    stacks_path.write_text(html, encoding="utf-8")


def _generate_breakpoints_page(
    output_dir: Path, db_path: str, records: list[dict[str, Any]]
) -> None:
    """Generate the breakpoints management page.

    Args:
        output_dir: Directory for output files.
        db_path: Path to the database.
        records: List of all call records.
    """
    port = read_port_file(get_discovery_file_path()) or 5174
    api_base = f"http://localhost:{port}/api"
    nav_header = _generate_navigation_header("breakpoints.html")

    # Get unique functions
    functions = sorted({r.get("function_name", "") for r in records if r.get("function_name")})

    functions_html = ""
    for func_name in functions:
        func_records = [r for r in records if r.get("function_name") == func_name]
        functions_html += f"""
        <div class="function-card" data-function="{_escape_text(func_name)}">
            <div class="function-header">
                <span class="function-name">{_escape_text(func_name)}()</span>
                <span class="function-calls">{_escape_text(len(func_records))} call(s)</span>
            </div>
            <div class="breakpoint-controls">
                <button class="btn btn-set" onclick="setBreakpoint('{_escape_text(func_name)}')">
                    ➕ Set Breakpoint
                </button>
                <button class="btn btn-remove" onclick="removeBreakpoint('{_escape_text(func_name)}')" style="display:none;">
                    ❌ Remove Breakpoint
                </button>
                <span class="breakpoint-status-indicator" style="display:none;">
                    🔴 Active
                </span>
            </div>
        </div>
"""

    html = _render_template(
        "breakpoints.html",
        {
            "NAV_HEADER": nav_header,
            "API_BASE": json.dumps(api_base),
            "FUNCTIONS_HTML": functions_html if functions_html else "<p>No functions found.</p>",
        },
    )

    breakpoints_path = output_dir / "breakpoints.html"
    breakpoints_path.write_text(html, encoding="utf-8")
