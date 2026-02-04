"""Source Code Viewer with Syntax Highlighting.

This module provides utilities to generate HTML views of source code files
with syntax highlighting and navigation capabilities.
"""

import html
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name

TEMPLATES_DIR = Path(__file__).with_name("templates")


def _escape_text(value: object) -> str:
    return html.escape(str(value), quote=True)


def _render_template(name: str, replacements: dict[str, str]) -> str:
    template_path = TEMPLATES_DIR / name
    template = template_path.read_text(encoding="utf-8")
    for key, value in replacements.items():
        template = template.replace(f"__{key}__", value)
    return template


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

    return _render_template(
        "source_view.html",
        {
            "TITLE": _escape_text(title),
            "CONTEXT_HTML": context_html,
            "HIGHLIGHTED_CODE": highlighted_code,
            "CSS_STYLES": css_styles,
        },
    )


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
    html_out = '<div class="context-section">\n'
    html_out += '    <div class="section-title">Call Context</div>\n'

    # Timestamp and Parameters
    if "timestamp" in call_record:
        timestamp = call_record["timestamp"]
        dt = datetime.fromtimestamp(timestamp)
        timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        html_out += f"""
    <div class="section">
        <div class="section-title">Timestamp:</div>
        <div class="info-block">{_escape_text(timestamp_str)}</div>
    </div>
"""

    if "args" in call_record:
        args_str = json.dumps(call_record["args"], indent=2)
        html_out += f"""
    <div class="section">
        <div class="section-title">Parameters:</div>
        <div class="info-block">{_escape_text(args_str)}</div>
    </div>
"""

    # Callstack
    if "callstack" in call_record and call_record["callstack"]:
        html_out += """
    <div class="section">
        <div class="section-title">Call Stack:</div>
"""
        for i, frame in enumerate(call_record["callstack"]):
            html_out += f"""
        <div class="callstack-frame">
            <strong>Frame {i}:</strong> {_escape_text(frame.get('function', 'N/A'))}<br>
            <strong>File:</strong> {_escape_text(frame.get('filename', 'N/A'))}<br>
            <strong>Line:</strong> {_escape_text(frame.get('lineno', 'N/A'))}<br>
"""
            if frame.get("code_context"):
                code_ctx = frame["code_context"]
                html_out += (
                    "            <strong>Code:</strong> <code>"
                    f"{_escape_text(code_ctx)}</code><br>\n"
                )
            html_out += "        </div>\n"
        html_out += "    </div>\n"

    # Navigation
    if db_path and "id" in call_record:
        html_out += _generate_navigation_section(call_record["id"], db_path)

    html_out += "</div>\n"
    return html_out


def _generate_navigation_section(call_id: int, db_path: str) -> str:
    """Generate navigation links section.

    Args:
        call_id: Current call record ID.
        db_path: Database path for looking up navigation targets.

    Returns:
        HTML string for the navigation section.
    """
    from .cas_store import CASStore

    store = CASStore(db_path)
    current_record = store.get_call_record(call_id)

    if current_record is None:
        store.close()
        return ""

    html_out = """
    <div class="navigation">
        <div class="section-title">Navigation</div>
        <div class="nav-links">
"""

    # Previous by timestamp
    prev_time = store.get_previous_call_by_timestamp(call_id)
    if prev_time:
        link = _create_source_link(prev_time, db_path)
        html_out += (
            f'            <a href="{_escape_text(link)}" '
            'class="nav-link">← Previous (Timestamp)</a>\n'
        )
    else:
        html_out += (
            '            <span class="nav-link" style="background-color: #ccc;">'
            "← Previous (Timestamp)</span>\n"
        )

    # Next by timestamp
    next_time = store.get_next_call_by_timestamp(call_id)
    if next_time:
        link = _create_source_link(next_time, db_path)
        html_out += (
            f'            <a href="{_escape_text(link)}" '
            'class="nav-link">Next (Timestamp) →</a>\n'
        )
    else:
        html_out += (
            '            <span class="nav-link" style="background-color: #ccc;">'
            "Next (Timestamp) →</span>\n"
        )

    # Previous same function
    prev_func = store.get_previous_call_of_same_function(call_id)
    if prev_func:
        link = _create_source_link(prev_func, db_path)
        func_name = current_record.get("function_name", "function")
        html_out += (
            f'            <a href="{_escape_text(link)}" class="nav-link">'
            f"← Previous {_escape_text(func_name)}()</a>\n"
        )
    else:
        func_name = current_record.get("function_name", "function")
        html_out += (
            f'            <span class="nav-link" style="background-color: #ccc;">'
            f"← Previous {_escape_text(func_name)}()</span>\n"
        )

    # Next same function
    next_func = store.get_next_call_of_same_function(call_id)
    if next_func:
        link = _create_source_link(next_func, db_path)
        func_name = current_record.get("function_name", "function")
        html_out += (
            f'            <a href="{_escape_text(link)}" class="nav-link">'
            f"Next {_escape_text(func_name)}() →</a>\n"
        )
    else:
        func_name = current_record.get("function_name", "function")
        html_out += (
            f'            <span class="nav-link" style="background-color: #ccc;">'
            f"Next {_escape_text(func_name)}() →</span>\n"
        )

    html_out += """
        </div>
    </div>
"""

    store.close()
    return html_out


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
    return (
        f'<a href="{_escape_text(link_url)}" '
        'style="color: #2196F3; text-decoration: none;">'
        f"{_escape_text(link_text)}</a>"
    )


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

    return _render_template(
        "frame_view.html",
        {
            "TITLE": _escape_text(title),
            "CONTEXT_HTML": context_html,
            "HIGHLIGHTED_CODE": highlighted_code,
            "CSS_STYLES": css_styles,
        },
    )


def _generate_frame_context_section(
    call_record: dict[str, Any], frame_index: int, db_path: Optional[str] = None
) -> str:
    """Generate context section for frame view."""
    html_out = '<div class="context-section">\n'
    html_out += f'    <div class="section-title">Frame {frame_index} Context</div>\n'

    callstack = call_record.get("callstack", [])
    if frame_index < len(callstack):
        frame = callstack[frame_index]
        html_out += f"""
    <div class="section">
        <div class="section-title">Function:</div>
        <div class="info-block">{_escape_text(frame.get('function', 'N/A'))}</div>
    </div>
    <div class="section">
        <div class="section-title">File:</div>
        <div class="info-block">{_escape_text(frame.get('filename', 'N/A'))}</div>
    </div>
    <div class="section">
        <div class="section-title">Line:</div>
        <div class="info-block">{_escape_text(frame.get('lineno', 'N/A'))}</div>
    </div>
"""
        if frame.get("code_context"):
            html_out += f"""
    <div class="section">
        <div class="section-title">Code Context:</div>
        <div class="info-block">{_escape_text(frame.get('code_context'))}</div>
    </div>
"""

    # Navigation
    if db_path and "id" in call_record:
        html_out += _generate_navigation_section(call_record["id"], db_path)

    html_out += "</div>\n"
    return html_out
