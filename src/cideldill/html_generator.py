"""HTML Generator for CAS Store Database Viewer.

This module provides utilities to generate HTML views of CAS Store database content,
particularly for visualizing function call records from the calculator examples.
"""

import json
from pathlib import Path
from typing import Any


def generate_html_viewer(db_path: str, output_path: str, title: str = "CAS Store Viewer") -> None:
    """Generate an HTML viewer for a CAS Store database.

    Args:
        db_path: Path to the SQLite database file.
        output_path: Path where the HTML file should be written.
        title: Title for the HTML page.
    """
    # Read data from database using CASStore
    from cideldill import CASStore

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

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
        }}
        .info {{
            background-color: #e3f2fd;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }}
        .record {{
            background-color: white;
            border: 1px solid #ddd;
            border-radius: 5px;
            padding: 15px;
            margin-bottom: 15px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .record-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            padding-bottom: 10px;
            border-bottom: 1px solid #eee;
        }}
        .function-name {{
            font-size: 1.2em;
            font-weight: bold;
            color: #1976D2;
        }}
        .record-id {{
            color: #666;
            font-size: 0.9em;
        }}
        .section {{
            margin: 10px 0;
        }}
        .section-title {{
            font-weight: bold;
            color: #555;
            margin-bottom: 5px;
        }}
        .code-block {{
            background-color: #f8f8f8;
            border: 1px solid #e0e0e0;
            border-radius: 3px;
            padding: 10px;
            overflow-x: auto;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
        }}
        .result {{
            color: #2E7D32;
        }}
        .exception {{
            color: #C62828;
        }}
        .timestamp {{
            color: #777;
            font-size: 0.85em;
        }}
        .summary {{
            background-color: #fff3cd;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            border-left: 4px solid #ffc107;
        }}
    </style>
</head>
<body>
    {nav_header}

    <h1>{title}</h1>

    <div class="info">
        <strong>Database:</strong> {db_path}
    </div>

    <div class="summary">
        <strong>Total Function Calls:</strong> {len(records)}
    </div>

    <h2>Function Call Records</h2>

    {records_html}

    <div style="margin-top: 30px; padding: 20px; background-color: #e8f5e9; \
border-radius: 5px; text-align: center;">
        <strong>✓ All records loaded successfully!</strong>
    </div>
</body>
</html>
"""
    return html


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
            <span class="function-name">{record['function_name']}()</span>
            <span class="record-id">Record #{record['id']}</span>
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
            <div class="timestamp">{timestamp_str} (Unix: {timestamp})</div>
        </div>
"""

    # Call Site
    if "call_site" in record:
        call_site = record["call_site"]
        source_link = ""
        if db_path and "id" in record:
            link_url = f"source_{record['id']}.html"
            link_style = "color: #2196F3; text-decoration: none; font-weight: bold;"
            source_link = f' <a href="{link_url}" style="{link_style}">[View Source]</a>'
        html += f"""
        <div class="section">
            <div class="section-title">Call Site:{source_link}</div>
            <div class="code-block">
                <strong>File:</strong> {call_site.get('filename', 'N/A')}<br>
                <strong>Line:</strong> {call_site.get('lineno', 'N/A')}<br>
                <strong>Function:</strong> {call_site.get('function', 'N/A')}<br>
"""
        if call_site.get('code_context'):
            code_ctx = call_site['code_context']
            html += f"                <strong>Code:</strong> <code>{code_ctx}</code><br>\n"
        html += """            </div>
        </div>
"""

    # Arguments
    if "args" in record:
        args_str = json.dumps(record["args"], indent=2)
        html += f"""
        <div class="section">
            <div class="section-title">Arguments:</div>
            <div class="code-block">{args_str}</div>
        </div>
"""

    # Result
    if "result" in record:
        result_str = json.dumps(record["result"], indent=2)
        html += f"""
        <div class="section">
            <div class="section-title result">Result:</div>
            <div class="code-block result">{result_str}</div>
        </div>
"""

    # Exception
    if "exception" in record:
        exception_str = json.dumps(record["exception"], indent=2)
        html += f"""
        <div class="section">
            <div class="section-title exception">Exception:</div>
            <div class="code-block exception">{exception_str}</div>
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
                frame_link = f' <a href="{link_url}" style="{link_style}">[view]</a>'
            html += f"""                <div style="{frame_style}">
                    <strong>Frame {i}:</strong> {frame.get('function', 'N/A')}{frame_link}<br>
                    <strong>File:</strong> {frame.get('filename', 'N/A')}<br>
                    <strong>Line:</strong> {frame.get('lineno', 'N/A')}<br>
"""
            if frame.get('code_context'):
                code_ctx = frame['code_context']
                html += f"                    <strong>Code:</strong> <code>{code_ctx}</code><br>\n"
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
    from cideldill import CASStore
    from cideldill.source_viewer import generate_frame_view, generate_source_view

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

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CID el Dill Viewer - Home</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }}
        .stat-card {{
            background-color: white;
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            text-align: center;
        }}
        .stat-value {{
            font-size: 3em;
            font-weight: bold;
            color: #2196F3;
            margin: 10px 0;
        }}
        .stat-label {{
            font-size: 1.1em;
            color: #666;
        }}
        .quick-links {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }}
        .quick-link-card {{
            background-color: white;
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 30px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            text-align: center;
            text-decoration: none;
            color: inherit;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .quick-link-card:hover {{
            transform: translateY(-4px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
        }}
        .quick-link-icon {{
            font-size: 3em;
            margin-bottom: 15px;
        }}
        .quick-link-title {{
            font-size: 1.3em;
            font-weight: bold;
            color: #333;
            margin-bottom: 10px;
        }}
        .quick-link-desc {{
            color: #666;
            font-size: 0.95em;
        }}
    </style>
</head>
<body>
    <div class="container">
        {nav_header}

        <h1>Welcome to CID el Dill Viewer</h1>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value">{total_calls}</div>
                <div class="stat-label">Total Function Calls</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{unique_functions}</div>
                <div class="stat-label">Unique Functions</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{unique_files}</div>
                <div class="stat-label">Source Files</div>
            </div>
        </div>

        <h2>Quick Access</h2>
        <div class="quick-links">
            <a href="timeline.html" class="quick-link-card">
                <div class="quick-link-icon">📊</div>
                <div class="quick-link-title">Timeline View</div>
                <div class="quick-link-desc">View all function calls chronologically</div>
            </a>

            <a href="sources.html" class="quick-link-card">
                <div class="quick-link-icon">📄</div>
                <div class="quick-link-title">Source Files</div>
                <div class="quick-link-desc">Browse all source files with calls</div>
            </a>

            <a href="callstacks.html" class="quick-link-card">
                <div class="quick-link-icon">📚</div>
                <div class="quick-link-title">Call Stacks</div>
                <div class="quick-link-desc">Explore function call stacks</div>
            </a>

            <a href="breakpoints.html" class="quick-link-card">
                <div class="quick-link-icon">🔴</div>
                <div class="quick-link-title">Breakpoints</div>
                <div class="quick-link-desc">View and manage breakpoints</div>
            </a>
        </div>

        <div style="margin-top: 40px; padding: 20px; background-color: #e8f5e9;
                    border-radius: 5px; border-left: 4px solid #4CAF50;">
            <strong>Database:</strong> {db_path}
        </div>
    </div>
</body>
</html>
"""

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
    sorted_records = sorted(records, key=lambda r: r.get('timestamp', 0))

    timeline_html = ""
    for record in sorted_records:
        timestamp = record.get('timestamp', 0)
        from datetime import datetime
        dt = datetime.fromtimestamp(timestamp)
        timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        result_str = "Exception" if "exception" in record else str(record.get('result', 'N/A'))
        link_url = f"source_{record['id']}.html"

        timeline_html += f"""
        <div class="timeline-item">
            <div class="timeline-time">{timestamp_str}</div>
            <div class="timeline-content">
                <div class="timeline-function">{record.get('function_name', 'Unknown')}()</div>
                <div class="timeline-result">Result: {result_str}</div>
                <a href="{link_url}" class="timeline-link">View Details →</a>
            </div>
        </div>
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Timeline View</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
        }}
        .timeline-item {{
            background-color: white;
            border-left: 4px solid #2196F3;
            padding: 20px;
            margin-bottom: 15px;
            border-radius: 4px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .timeline-time {{
            color: #666;
            font-size: 0.9em;
            margin-bottom: 8px;
        }}
        .timeline-function {{
            font-size: 1.3em;
            font-weight: bold;
            color: #1976D2;
            margin-bottom: 5px;
        }}
        .timeline-result {{
            color: #555;
            margin-bottom: 10px;
        }}
        .timeline-link {{
            color: #2196F3;
            text-decoration: none;
            font-weight: bold;
        }}
        .timeline-link:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        {nav_header}

        <h1>Timeline View</h1>
        <p>All function calls ordered by time</p>

        {timeline_html}
    </div>
</body>
</html>
"""

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
        filename = record.get('call_site', {}).get('filename')
        if filename:
            if filename not in files_dict:
                files_dict[filename] = []
            files_dict[filename].append(record)

    files_html = ""
    for filename, file_records in sorted(files_dict.items()):
        files_html += f"""
        <div class="file-card">
            <div class="file-name">{filename}</div>
            <div class="file-stats">{len(file_records)} call(s)</div>
            <div class="file-calls">
"""
        for record in file_records[:5]:  # Show first 5 calls
            link_url = f"source_{record['id']}.html"
            files_html += f"""
                <a href="{link_url}" class="call-link">
                    {record.get('function_name', 'Unknown')}()
                    [Line {record.get('call_site', {}).get('lineno', '?')}]
                </a>
"""
        if len(file_records) > 5:
            files_html += f'<div class="more">... and {len(file_records) - 5} more</div>'

        files_html += """
            </div>
        </div>
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Source Files</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
        }}
        .file-card {{
            background-color: white;
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .file-name {{
            font-size: 1.2em;
            font-weight: bold;
            color: #1976D2;
            margin-bottom: 10px;
            word-break: break-all;
        }}
        .file-stats {{
            color: #666;
            margin-bottom: 15px;
        }}
        .file-calls {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        .call-link {{
            color: #2196F3;
            text-decoration: none;
            padding: 8px;
            background-color: #f8f8f8;
            border-radius: 4px;
            transition: background-color 0.2s;
        }}
        .call-link:hover {{
            background-color: #e3f2fd;
        }}
        .more {{
            color: #666;
            font-style: italic;
            padding: 8px;
        }}
    </style>
</head>
<body>
    <div class="container">
        {nav_header}

        <h1>Source Files</h1>
        <p>All source files with recorded function calls</p>

        {files_html if files_html else '<p>No source files found.</p>'}
    </div>
</body>
</html>
"""

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
        if not record.get('callstack'):
            continue

        callstack = record.get('callstack', [])
        link_url = f"source_{record['id']}.html"

        stacks_html += f"""
        <div class="stack-card">
            <div class="stack-header">
                <span class="stack-function">{record.get('function_name', 'Unknown')}()</span>
                <span class="stack-depth">Depth: {len(callstack)}</span>
            </div>
            <div class="stack-frames">
"""
        for i, frame in enumerate(callstack[:5]):  # Show first 5 frames
            stacks_html += f"""
                <div class="stack-frame">
                    Frame {i}: {frame.get('function', 'Unknown')}
                    [{frame.get('filename', 'Unknown')}:{frame.get('lineno', '?')}]
                </div>
"""
        if len(callstack) > 5:
            stacks_html += f"<div class='more'>... and {len(callstack) - 5} more frames</div>"

        stacks_html += f"""
            </div>
            <a href="{link_url}" class="view-link">View Full Stack →</a>
        </div>
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Call Stacks</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
        }}
        .stack-card {{
            background-color: white;
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .stack-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #eee;
        }}
        .stack-function {{
            font-size: 1.2em;
            font-weight: bold;
            color: #1976D2;
        }}
        .stack-depth {{
            color: #666;
            font-size: 0.9em;
        }}
        .stack-frames {{
            background-color: #f8f8f8;
            padding: 15px;
            border-radius: 4px;
            margin-bottom: 15px;
        }}
        .stack-frame {{
            padding: 8px;
            margin-bottom: 5px;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
            color: #333;
        }}
        .view-link {{
            color: #2196F3;
            text-decoration: none;
            font-weight: bold;
        }}
        .view-link:hover {{
            text-decoration: underline;
        }}
        .more {{
            color: #666;
            font-style: italic;
            padding: 8px;
        }}
    </style>
</head>
<body>
    <div class="container">
        {nav_header}

        <h1>Call Stacks</h1>
        <p>All recorded function call stacks</p>

        {stacks_html if stacks_html else '<p>No call stacks found.</p>'}
    </div>
</body>
</html>
"""

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
    nav_header = _generate_navigation_header("breakpoints.html")

    # Get unique functions
    functions = sorted({r.get('function_name', '') for r in records if r.get('function_name')})

    functions_html = ""
    for func_name in functions:
        func_records = [r for r in records if r.get('function_name') == func_name]
        functions_html += f"""
        <div class="function-card">
            <div class="function-header">
                <span class="function-name">{func_name}()</span>
                <span class="function-calls">{len(func_records)} call(s)</span>
            </div>
            <div class="breakpoint-info">
                <span class="breakpoint-status">
                    ℹ️ Breakpoint management is available in the live inspector
                </span>
            </div>
        </div>
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Breakpoints</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
        }}
        .info-box {{
            background-color: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px;
            margin-bottom: 20px;
            border-radius: 4px;
        }}
        .function-card {{
            background-color: white;
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 15px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .function-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }}
        .function-name {{
            font-size: 1.2em;
            font-weight: bold;
            color: #1976D2;
        }}
        .function-calls {{
            color: #666;
            font-size: 0.9em;
        }}
        .breakpoint-info {{
            padding: 10px;
            background-color: #f8f8f8;
            border-radius: 4px;
            color: #666;
        }}
        .breakpoint-status {{
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="container">
        {nav_header}

        <h1>Breakpoints</h1>

        <div class="info-box">
            <strong>Note:</strong> This page shows functions available for breakpoint management.
            To set/unset breakpoints during execution, use the Interceptor API in your code:
            <ul>
                <li>
                    <code>interceptor.set_breakpoint(function_name)</code>
                    - Set breakpoint on a function
                </li>
                <li>
                    <code>interceptor.remove_breakpoint(function_name)</code>
                    - Remove breakpoint
                </li>
                <li><code>interceptor.set_breakpoint_on_all()</code> - Break on all functions</li>
                <li><code>interceptor.clear_breakpoints()</code> - Clear all breakpoints</li>
            </ul>
        </div>

        <h2>Available Functions</h2>
        {functions_html if functions_html else '<p>No functions found.</p>'}
    </div>
</body>
</html>
"""

    breakpoints_path = output_dir / "breakpoints.html"
    breakpoints_path.write_text(html, encoding="utf-8")


