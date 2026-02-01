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
        records_html += _format_record(record)
    
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
    
    <div style="margin-top: 30px; padding: 20px; background-color: #e8f5e9; border-radius: 5px; text-align: center;">
        <strong>✓ All records loaded successfully!</strong>
    </div>
</body>
</html>
"""
    return html


def _format_record(record: dict[str, Any]) -> str:
    """Format a single call record as HTML.

    Args:
        record: Call record dictionary.

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
    
    html += """
    </div>
"""
    
    return html
