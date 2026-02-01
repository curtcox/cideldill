#!/usr/bin/env python3
"""Generate HTML report from all tool outputs."""

import json
import os
from datetime import datetime
from pathlib import Path


def read_file_safe(filepath: str) -> str:
    """Read file safely, return empty string if not exists."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ""


def read_json_safe(filepath: str) -> dict:
    """Read JSON file safely, return empty dict if not exists."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def count_issues(data: str, keywords: list[str]) -> int:
    """Count issues in text data."""
    count = 0
    for keyword in keywords:
        count += data.lower().count(keyword.lower())
    return count


def generate_badge(label: str, value: str, color: str) -> str:
    """Generate SVG badge HTML."""
    return f'<span class="badge badge-{color}">{label}: {value}</span>'


def main() -> None:
    """Generate the main HTML report."""
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    
    # Read all report data
    ruff_txt = read_file_safe("reports/ruff.txt")
    pylint_txt = read_file_safe("reports/pylint.txt")
    mypy_txt = read_file_safe("reports/mypy-txt/index.txt")
    pydoclint_txt = read_file_safe("reports/pydoclint.txt")
    radon_cc_txt = read_file_safe("reports/radon-cc.txt")
    radon_mi_txt = read_file_safe("reports/radon-mi.txt")
    vulture_txt = read_file_safe("reports/vulture.txt")
    shellcheck_txt = read_file_safe("reports/shellcheck.txt")
    hadolint_txt = read_file_safe("reports/hadolint.txt")
    eslint_txt = read_file_safe("reports/eslint.txt")
    stylelint_txt = read_file_safe("reports/stylelint.txt")
    pytest_txt = read_file_safe("reports/pytest.txt")
    
    # Count issues
    ruff_issues = ruff_txt.count("\n") if ruff_txt else 0
    pylint_issues = count_issues(pylint_txt, ["warning", "error"])
    mypy_issues = count_issues(mypy_txt, ["error"])
    pydoclint_issues = count_issues(pydoclint_txt, ["DOC"])
    vulture_issues = vulture_txt.count("unused")
    shellcheck_issues = shellcheck_txt.count("SC")
    hadolint_issues = hadolint_txt.count("DL")
    eslint_issues = count_issues(eslint_txt, ["error", "warning"])
    stylelint_issues = count_issues(stylelint_txt, ["error", "warning"])
    
    # Extract coverage
    coverage_json = read_json_safe("reports/coverage.json")
    coverage_percent = coverage_json.get("totals", {}).get("percent_covered", 0)
    
    # Get test results
    test_passed = "passed" in pytest_txt.lower()
    
    # Generate HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CID el Dill - Build Report</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
            overflow: hidden;
        }}
        header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }}
        h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
        }}
        .subtitle {{
            font-size: 1.2em;
            opacity: 0.9;
        }}
        .timestamp {{
            margin-top: 10px;
            font-size: 0.9em;
            opacity: 0.8;
        }}
        .content {{
            padding: 40px;
        }}
        .summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }}
        .summary-card {{
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }}
        .summary-card h3 {{
            font-size: 0.9em;
            color: #666;
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .summary-card .value {{
            font-size: 2em;
            font-weight: bold;
            color: #333;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.85em;
            font-weight: 600;
            margin-right: 8px;
        }}
        .badge-success {{ background: #d4edda; color: #155724; }}
        .badge-warning {{ background: #fff3cd; color: #856404; }}
        .badge-danger {{ background: #f8d7da; color: #721c24; }}
        .badge-info {{ background: #d1ecf1; color: #0c5460; }}
        .section {{
            margin-bottom: 40px;
        }}
        .section h2 {{
            color: #667eea;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}
        .report-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
        }}
        .report-card {{
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            border: 1px solid #dee2e6;
        }}
        .report-card h3 {{
            color: #495057;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        .report-card pre {{
            background: white;
            padding: 15px;
            border-radius: 4px;
            overflow-x: auto;
            font-size: 0.85em;
            border: 1px solid #dee2e6;
            max-height: 300px;
            overflow-y: auto;
        }}
        .report-card a {{
            color: #667eea;
            text-decoration: none;
            font-weight: 600;
        }}
        .report-card a:hover {{
            text-decoration: underline;
        }}
        footer {{
            background: #f8f9fa;
            padding: 20px;
            text-align: center;
            color: #666;
            border-top: 1px solid #dee2e6;
        }}
        .status-icon {{
            font-size: 1.2em;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🔍 CID el Dill</h1>
            <div class="subtitle">Comprehensive Build Report</div>
            <div class="timestamp">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")}</div>
        </header>
        
        <div class="content">
            <div class="summary">
                <div class="summary-card">
                    <h3>Coverage</h3>
                    <div class="value">{coverage_percent:.1f}%</div>
                </div>
                <div class="summary-card">
                    <h3>Total Issues</h3>
                    <div class="value">{ruff_issues + pylint_issues + mypy_issues}</div>
                </div>
                <div class="summary-card">
                    <h3>Tests Status</h3>
                    <div class="value">{"✓ Pass" if test_passed else "✗ Fail"}</div>
                </div>
            </div>

            <section class="section">
                <h2>🐍 Python Code Quality</h2>
                <div class="report-grid">
                    <div class="report-card">
                        <h3>
                            Ruff
                            {generate_badge("Issues", str(ruff_issues), "success" if ruff_issues == 0 else "warning")}
                        </h3>
                        <pre>{ruff_txt if ruff_txt else "No issues found ✓"}</pre>
                    </div>
                    <div class="report-card">
                        <h3>
                            Pylint
                            {generate_badge("Issues", str(pylint_issues), "success" if pylint_issues < 5 else "warning")}
                        </h3>
                        <pre>{pylint_txt[:1000] if pylint_txt else "No issues found ✓"}</pre>
                    </div>
                    <div class="report-card">
                        <h3>
                            Mypy
                            {generate_badge("Errors", str(mypy_issues), "success" if mypy_issues == 0 else "danger")}
                        </h3>
                        <pre>{mypy_txt[:1000] if mypy_txt else "No type errors ✓"}</pre>
                        <a href="mypy-html/index.html">View Full Report →</a>
                    </div>
                    <div class="report-card">
                        <h3>
                            Pydoclint
                            {generate_badge("Issues", str(pydoclint_issues), "success" if pydoclint_issues == 0 else "warning")}
                        </h3>
                        <pre>{pydoclint_txt[:1000] if pydoclint_txt else "All docstrings valid ✓"}</pre>
                    </div>
                </div>
            </section>

            <section class="section">
                <h2>📊 Code Metrics</h2>
                <div class="report-grid">
                    <div class="report-card">
                        <h3>Radon - Complexity</h3>
                        <pre>{radon_cc_txt[:1000] if radon_cc_txt else "No complexity issues ✓"}</pre>
                    </div>
                    <div class="report-card">
                        <h3>Radon - Maintainability</h3>
                        <pre>{radon_mi_txt[:1000] if radon_mi_txt else "Good maintainability ✓"}</pre>
                    </div>
                    <div class="report-card">
                        <h3>
                            Vulture
                            {generate_badge("Unused", str(vulture_issues), "success" if vulture_issues == 0 else "info")}
                        </h3>
                        <pre>{vulture_txt[:1000] if vulture_txt else "No dead code found ✓"}</pre>
                    </div>
                </div>
            </section>

            <section class="section">
                <h2>🐚 Shell & Docker</h2>
                <div class="report-grid">
                    <div class="report-card">
                        <h3>
                            ShellCheck
                            {generate_badge("Issues", str(shellcheck_issues), "success" if shellcheck_issues == 0 else "warning")}
                        </h3>
                        <pre>{shellcheck_txt[:1000] if shellcheck_txt else "No shell issues ✓"}</pre>
                    </div>
                    <div class="report-card">
                        <h3>
                            Hadolint
                            {generate_badge("Issues", str(hadolint_issues), "success" if hadolint_issues == 0 else "warning")}
                        </h3>
                        <pre>{hadolint_txt[:1000] if hadolint_txt else "Dockerfile is clean ✓"}</pre>
                    </div>
                </div>
            </section>

            <section class="section">
                <h2>🎨 Frontend Code Quality</h2>
                <div class="report-grid">
                    <div class="report-card">
                        <h3>
                            ESLint
                            {generate_badge("Issues", str(eslint_issues), "success" if eslint_issues == 0 else "warning")}
                        </h3>
                        <pre>{eslint_txt[:1000] if eslint_txt else "No JavaScript issues ✓"}</pre>
                    </div>
                    <div class="report-card">
                        <h3>
                            Stylelint
                            {generate_badge("Issues", str(stylelint_issues), "success" if stylelint_issues == 0 else "warning")}
                        </h3>
                        <pre>{stylelint_txt[:1000] if stylelint_txt else "No CSS issues ✓"}</pre>
                    </div>
                </div>
            </section>

            <section class="section">
                <h2>🧪 Testing & Coverage</h2>
                <div class="report-grid">
                    <div class="report-card">
                        <h3>
                            Unit Tests
                            {generate_badge("Status", "Pass" if test_passed else "Fail", "success" if test_passed else "danger")}
                        </h3>
                        <pre>{pytest_txt[:1000] if pytest_txt else "No test output"}</pre>
                    </div>
                    <div class="report-card">
                        <h3>
                            Coverage Report
                            {generate_badge("Coverage", f"{coverage_percent:.1f}%", "success" if coverage_percent > 80 else "warning")}
                        </h3>
                        <a href="coverage/index.html">View Full Coverage Report →</a>
                    </div>
                </div>
            </section>
        </div>
        
        <footer>
            <p>Generated by CID el Dill Build System | <a href="https://github.com/curtcox/cideldill">GitHub Repository</a></p>
        </footer>
    </div>
</body>
</html>
"""
    
    # Write the HTML file
    with open("reports/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    
    print("✓ HTML report generated successfully!")
    print(f"  - Total Python issues: {ruff_issues + pylint_issues + mypy_issues}")
    print(f"  - Coverage: {coverage_percent:.1f}%")
    print(f"  - Tests: {'PASSED' if test_passed else 'FAILED'}")


if __name__ == "__main__":
    main()
