from __future__ import annotations

import argparse
import html
from pathlib import Path
import xml.etree.ElementTree as ET


def render_report(xml_path: Path, html_path: Path, title: str) -> None:
    root = ET.parse(xml_path).getroot()
    suites = list(root.findall(".//testsuite")) if root.tag != "testsuite" else [root]

    rows: list[str] = []
    total_tests = total_failures = total_errors = total_skipped = 0
    total_time = 0.0

    for suite in suites:
        tests = int(suite.attrib.get("tests", "0"))
        failures = int(suite.attrib.get("failures", "0"))
        errors = int(suite.attrib.get("errors", "0"))
        skipped = int(suite.attrib.get("skipped", "0"))
        time_taken = float(suite.attrib.get("time", "0"))
        name = suite.attrib.get("name", "unnamed suite")

        total_tests += tests
        total_failures += failures
        total_errors += errors
        total_skipped += skipped
        total_time += time_taken

        rows.append(
            "<tr>"
            f"<td>{html.escape(name)}</td>"
            f"<td>{tests}</td>"
            f"<td>{failures}</td>"
            f"<td>{errors}</td>"
            f"<td>{skipped}</td>"
            f"<td>{time_taken:.3f}s</td>"
            "</tr>"
        )

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #0f172a; color: #e2e8f0; }}
    h1 {{ margin: 0 0 1rem 0; }}
    .summary {{ margin-bottom: 1rem; }}
    table {{ border-collapse: collapse; width: 100%; background: #111827; }}
    th, td {{ border: 1px solid #334155; padding: 0.6rem; text-align: left; }}
    th {{ background: #1f2937; }}
    .ok {{ color: #86efac; }}
    .warn {{ color: #fcd34d; }}
    .bad {{ color: #fca5a5; }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <div class="summary">
    <strong>Total:</strong> {total_tests} tests,
    <span class="{ 'bad' if (total_failures + total_errors) else 'ok' }">{total_failures} failures</span>,
    <span class="{ 'bad' if total_errors else 'ok' }">{total_errors} errors</span>,
    <span class="{ 'warn' if total_skipped else 'ok' }">{total_skipped} skipped</span>,
    {total_time:.3f}s
  </div>
  <table>
    <thead>
      <tr>
        <th>Suite</th><th>Tests</th><th>Failures</th><th>Errors</th><th>Skipped</th><th>Time</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</body>
</html>
"""
    html_path.write_text(html_doc, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert JUnit XML to static HTML summary.")
    parser.add_argument("--xml", required=True, type=Path)
    parser.add_argument("--html", required=True, type=Path)
    parser.add_argument("--title", default="Test Report")
    args = parser.parse_args()
    render_report(args.xml, args.html, args.title)


if __name__ == "__main__":
    main()
