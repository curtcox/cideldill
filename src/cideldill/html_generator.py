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
            # Add source link for each frame
            frame_link = ""
            if db_path and frame.get('filename') and frame.get('lineno'):
                link_url = f"source_{record['id']}.html"
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
    """Generate source viewer pages for all call records.

    Args:
        db_path: Path to the database.
        main_output_path: Path to the main HTML output file (used for determining output directory).
    """
    from cideldill import CASStore
    from cideldill.source_viewer import generate_source_view

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

