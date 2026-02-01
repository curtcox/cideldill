"""Source Code Viewer with Syntax Highlighting.

This module provides utilities to generate HTML views of source code files
with syntax highlighting and navigation capabilities.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name


def generate_source_view(
    source_file: str,
    output_path: str,
    highlight_line: Optional[int] = None,
    call_record: Optional[dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> None:
    """Generate an HTML view of a source file with syntax highlighting.

    Args:
        source_file: Path to the source file to display.
        output_path: Path where the HTML file should be written.
        highlight_line: Line number to highlight (1-indexed).
        call_record: Optional call record containing context information.
        db_path: Optional database path for generating navigation links.
    """
    # Read source file content
    source_content = Path(source_file).read_text(encoding="utf-8")

    # Generate HTML
    html_content = _generate_source_html(
        source_file=source_file,
        source_content=source_content,
        highlight_line=highlight_line,
        call_record=call_record,
        db_path=db_path,
    )

    # Write to file
    Path(output_path).write_text(html_content, encoding="utf-8")


def generate_frame_view(
    source_file: str,
    output_path: str,
    highlight_line: Optional[int] = None,
    call_record: Optional[dict[str, Any]] = None,
    frame_index: int = 0,
    db_path: Optional[str] = None,
) -> None:
    """Generate an HTML view of a source file for a specific stack frame.

    Args:
        source_file: Path to the source file to display.
        output_path: Path where the HTML file should be written.
        highlight_line: Line number to highlight (1-indexed).
        call_record: Optional call record containing context information.
        frame_index: Index of the frame in the callstack.
        db_path: Optional database path for generating navigation links.
    """
    # Read source file content
    source_content = Path(source_file).read_text(encoding="utf-8")

    # Generate HTML
    html_content = _generate_frame_html(
        source_file=source_file,
        source_content=source_content,
        highlight_line=highlight_line,
        call_record=call_record,
        frame_index=frame_index,
        db_path=db_path,
    )

    # Write to file
    Path(output_path).write_text(html_content, encoding="utf-8")


def _generate_source_html(
    source_file: str,
    source_content: str,
    highlight_line: Optional[int] = None,
    call_record: Optional[dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> str:
    """Generate the HTML content for source viewing.

    Args:
        source_file: Path to the source file.
        source_content: Content of the source file.
        highlight_line: Line number to highlight (1-indexed).
        call_record: Optional call record containing context information.
        db_path: Optional database path for generating navigation links.

    Returns:
        Complete HTML page as a string.
    """
    # Get lexer for Python
    lexer = get_lexer_by_name("python", stripall=True)

    # Configure formatter with line numbers and highlighting
    formatter = HtmlFormatter(
        linenos=True,
        cssclass="source",
        style="default",
        hl_lines=[highlight_line] if highlight_line else [],
        linenostart=1,
    )

    # Generate syntax-highlighted HTML
    highlighted_code = highlight(source_content, lexer, formatter)

    # Get CSS for syntax highlighting
    css_styles = formatter.get_style_defs(".source")

    # Generate call context section if provided
    context_html = ""
    if call_record:
        context_html = _generate_context_section(call_record, db_path)

    # Generate page title
    filename = os.path.basename(source_file)
    title = f"Source: {filename}"
    if highlight_line:
        title += f" (Line {highlight_line})"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
        }}
        .source-container {{
            background-color: white;
            border: 1px solid #ddd;
            border-radius: 5px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            overflow-x: auto;
        }}
        .context-section {{
            background-color: white;
            border: 1px solid #ddd;
            border-radius: 5px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .section {{
            margin: 15px 0;
        }}
        .section-title {{
            font-weight: bold;
            color: #555;
            margin-bottom: 8px;
            font-size: 1.1em;
        }}
        .info-block {{
            background-color: #f8f8f8;
            border: 1px solid #e0e0e0;
            border-radius: 3px;
            padding: 12px;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
        }}
        .navigation {{
            background-color: #e3f2fd;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }}
        .nav-links {{
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            margin-top: 10px;
        }}
        .nav-link {{
            padding: 8px 16px;
            background-color: #2196F3;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            font-size: 0.9em;
        }}
        .nav-link:hover {{
            background-color: #1976D2;
        }}
        .nav-link:disabled {{
            background-color: #ccc;
            cursor: not-allowed;
        }}
        .callstack-frame {{
            margin: 10px 0;
            padding: 10px;
            background-color: #f9f9f9;
            border-left: 3px solid #ddd;
        }}
        /* Pygments syntax highlighting styles */
        {css_styles}
        .source .hll {{
            background-color: #ffffcc;
            display: block;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{title}</h1>

        {context_html}

        <div class="source-container">
            {highlighted_code}
        </div>
    </div>
</body>
</html>
"""
    return html


def _generate_context_section(
    call_record: dict[str, Any],
    db_path: Optional[str] = None,
) -> str:
    """Generate the context section showing call information.

    Args:
        call_record: Call record containing context information.
        db_path: Optional database path for generating navigation links.

    Returns:
        HTML string for the context section.
    """
    html = '<div class="context-section">\n'
    html += '    <div class="section-title">Call Context</div>\n'

    # Timestamp and Parameters
    if "timestamp" in call_record:
        timestamp = call_record["timestamp"]
        dt = datetime.fromtimestamp(timestamp)
        timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        html += f"""
    <div class="section">
        <div class="section-title">Timestamp:</div>
        <div class="info-block">{timestamp_str}</div>
    </div>
"""

    if "args" in call_record:
        args_str = json.dumps(call_record["args"], indent=2)
        html += f"""
    <div class="section">
        <div class="section-title">Parameters:</div>
        <div class="info-block">{args_str}</div>
    </div>
"""

    # Callstack
    if "callstack" in call_record and call_record["callstack"]:
        html += """
    <div class="section">
        <div class="section-title">Call Stack:</div>
"""
        for i, frame in enumerate(call_record["callstack"]):
            html += f"""
        <div class="callstack-frame">
            <strong>Frame {i}:</strong> {frame.get('function', 'N/A')}<br>
            <strong>File:</strong> {frame.get('filename', 'N/A')}<br>
            <strong>Line:</strong> {frame.get('lineno', 'N/A')}<br>
"""
            if frame.get('code_context'):
                code_ctx = frame['code_context']
                html += f"            <strong>Code:</strong> <code>{code_ctx}</code><br>\n"
            html += "        </div>\n"
        html += "    </div>\n"

    # Navigation
    if db_path and "id" in call_record:
        html += _generate_navigation_section(call_record["id"], db_path)

    html += "</div>\n"
    return html


def _generate_navigation_section(call_id: int, db_path: str) -> str:
    """Generate navigation links section.

    Args:
        call_id: Current call record ID.
        db_path: Database path for looking up navigation targets.

    Returns:
        HTML string for the navigation section.
    """
    from cideldill import CASStore

    store = CASStore(db_path)
    current_record = store.get_call_record(call_id)

    if current_record is None:
        store.close()
        return ""

    html = """
    <div class="navigation">
        <div class="section-title">Navigation</div>
        <div class="nav-links">
"""

    # Previous by timestamp
    prev_time = store.get_previous_call_by_timestamp(call_id)
    if prev_time:
        link = _create_source_link(prev_time, db_path)
        html += f'            <a href="{link}" class="nav-link">← Previous (Timestamp)</a>\n'
    else:
        html += (
            '            <span class="nav-link" style="background-color: #ccc;">'
            "← Previous (Timestamp)</span>\n"
        )

    # Next by timestamp
    next_time = store.get_next_call_by_timestamp(call_id)
    if next_time:
        link = _create_source_link(next_time, db_path)
        html += f'            <a href="{link}" class="nav-link">Next (Timestamp) →</a>\n'
    else:
        html += (
            '            <span class="nav-link" style="background-color: #ccc;">'
            "Next (Timestamp) →</span>\n"
        )

    # Previous same function
    prev_func = store.get_previous_call_of_same_function(call_id)
    if prev_func:
        link = _create_source_link(prev_func, db_path)
        func_name = current_record.get('function_name', 'function')
        html += f'            <a href="{link}" class="nav-link">← Previous {func_name}()</a>\n'
    else:
        func_name = current_record.get('function_name', 'function')
        html += (
            f'            <span class="nav-link" style="background-color: #ccc;">'
            f"← Previous {func_name}()</span>\n"
        )

    # Next same function
    next_func = store.get_next_call_of_same_function(call_id)
    if next_func:
        link = _create_source_link(next_func, db_path)
        func_name = current_record.get('function_name', 'function')
        html += f'            <a href="{link}" class="nav-link">Next {func_name}() →</a>\n'
    else:
        func_name = current_record.get('function_name', 'function')
        html += (
            f'            <span class="nav-link" style="background-color: #ccc;">'
            f"Next {func_name}() →</span>\n"
        )

    html += """
        </div>
    </div>
"""

    store.close()
    return html


def _create_source_link(call_record: dict[str, Any], db_path: str) -> str:
    """Create a source viewer link for a call record.

    Args:
        call_record: Call record to link to.
        db_path: Database path.

    Returns:
        URL for the source viewer page.
    """
    call_site = call_record.get("call_site")
    if not call_site:
        return "#"

    call_id = call_record.get("id", 0)

    # Create a simple URL format: source_<call_id>.html
    return f"source_{call_id}.html"


def generate_source_link_html(
    call_record: dict[str, Any],
    db_path: str,
    link_text: str = "View Source",
) -> str:
    """Generate an HTML link to the source viewer for a call record.

    Args:
        call_record: Call record containing call site information.
        db_path: Database path.
        link_text: Text to display for the link.

    Returns:
        HTML anchor tag as a string.
    """
    link_url = _create_source_link(call_record, db_path)
    return f'<a href="{link_url}" style="color: #2196F3; text-decoration: none;">{link_text}</a>'


def _generate_frame_html(
    source_file: str,
    source_content: str,
    highlight_line: Optional[int] = None,
    call_record: Optional[dict[str, Any]] = None,
    frame_index: int = 0,
    db_path: Optional[str] = None,
) -> str:
    """Generate the HTML content for frame viewing.

    Args:
        source_file: Path to the source file.
        source_content: Content of the source file.
        highlight_line: Line number to highlight (1-indexed).
        call_record: Optional call record containing context information.
        frame_index: Index of the frame in the callstack.
        db_path: Optional database path for generating navigation links.

    Returns:
        Complete HTML page as a string.
    """
    # Get lexer for Python
    lexer = get_lexer_by_name("python", stripall=True)

    # Configure formatter with line numbers and highlighting
    formatter = HtmlFormatter(
        linenos=True,
        cssclass="source",
        style="default",
        hl_lines=[highlight_line] if highlight_line else [],
        linenostart=1,
    )

    # Generate syntax-highlighted HTML
    highlighted_code = highlight(source_content, lexer, formatter)

    # Get CSS for syntax highlighting
    css_styles = formatter.get_style_defs(".source")

    # Generate frame context section if provided
    context_html = ""
    if call_record:
        context_html = _generate_frame_context_section(call_record, frame_index, db_path)

    # Generate page title
    filename = os.path.basename(source_file)
    title = f"Frame {frame_index}: {filename}"
    if highlight_line:
        title += f" (Line {highlight_line})"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
        }}
        .source-container {{
            background-color: white;
            border: 1px solid #ddd;
            border-radius: 5px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            overflow-x: auto;
        }}
        .context-section {{
            background-color: white;
            border: 1px solid #ddd;
            border-radius: 5px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .section {{
            margin: 15px 0;
        }}
        .section-title {{
            font-weight: bold;
            color: #555;
            margin-bottom: 8px;
            font-size: 1.1em;
        }}
        .info-block {{
            background-color: #f8f8f8;
            border: 1px solid #e0e0e0;
            border-radius: 3px;
            padding: 12px;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
        }}
        .navigation {{
            background-color: #e3f2fd;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }}
        .nav-links {{
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            margin-top: 10px;
        }}
        .nav-link {{
            padding: 8px 16px;
            background-color: #2196F3;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            font-size: 0.9em;
        }}
        .nav-link:hover {{
            background-color: #1976D2;
        }}
        .nav-link:disabled {{
            background-color: #ccc;
            cursor: not-allowed;
        }}
        .frame-info {{
            margin: 10px 0;
            padding: 10px;
            background-color: #fff3cd;
            border-left: 3px solid #ffc107;
        }}
        /* Pygments syntax highlighting styles */
        {css_styles}
        .source .hll {{
            background-color: #ffffcc;
            display: block;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{title}</h1>

        {context_html}

        <div class="source-container">
            {highlighted_code}
        </div>
    </div>
</body>
</html>
"""
    return html


def _generate_frame_context_section(
    call_record: dict[str, Any],
    frame_index: int,
    db_path: Optional[str] = None,
) -> str:
    """Generate the context section showing frame information.

    Args:
        call_record: Call record containing context information.
        frame_index: Index of the frame in the callstack.
        db_path: Optional database path for generating navigation links.

    Returns:
        HTML string for the frame context section.
    """
    html = '<div class="context-section">\n'
    html += f'    <div class="section-title">Frame {frame_index} Context</div>\n'

    callstack = call_record.get("callstack", [])
    if frame_index >= len(callstack):
        html += "</div>\n"
        return html

    frame = callstack[frame_index]

    # Frame details
    html += f"""
    <div class="frame-info">
        <strong>Function:</strong> {frame.get('function', 'N/A')}<br>
        <strong>File:</strong> {frame.get('filename', 'N/A')}<br>
        <strong>Line:</strong> {frame.get('lineno', 'N/A')}<br>
"""
    if frame.get('code_context'):
        code_ctx = frame['code_context']
        html += f"        <strong>Code:</strong> <code>{code_ctx}</code><br>\n"
    html += "    </div>\n"

    # Parent frame (caller)
    if frame_index + 1 < len(callstack):
        parent_frame = callstack[frame_index + 1]
        html += """
    <div class="section">
        <div class="section-title">Parent Frame (Caller):</div>
        <div class="info-block">
"""
        func_name = parent_frame.get('function', 'N/A')
        html += f"            <strong>Function:</strong> {func_name}<br>\n"
        file_name = parent_frame.get('filename', 'N/A')
        html += f"            <strong>File:</strong> {file_name}<br>\n"
        line_no = parent_frame.get('lineno', 'N/A')
        html += f"            <strong>Line:</strong> {line_no}<br>\n"
        if parent_frame.get('code_context'):
            parent_code_ctx = parent_frame['code_context']
            html += f"            <strong>Code:</strong> <code>{parent_code_ctx}</code><br>\n"
        # Add link to parent frame
        if db_path and call_record.get('id'):
            parent_link = f"frame_{call_record['id']}_{frame_index + 1}.html"
            link_style = "color: #2196F3; text-decoration: none;"
            html += (
                f'            <a href="{parent_link}" '
                f'style="{link_style}">[View Parent Frame]</a><br>\n'
            )
        html += """        </div>
    </div>
"""

    # Arguments (if this is the first frame - the actual function call)
    if frame_index == 0 and "args" in call_record:
        args_str = json.dumps(call_record["args"], indent=2)
        html += f"""
    <div class="section">
        <div class="section-title">Function Arguments:</div>
        <div class="info-block">{args_str}</div>
    </div>
"""

    html += "</div>\n"
    return html

