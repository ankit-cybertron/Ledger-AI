"""
pages/reports.py — assembles the context dict for templates/reports.html.

Reads the reconciliation engine's own generated report
(data/results/reconciliation_report.md) and does a small, dependency-free
markdown-to-HTML pass (headings, bold, bullet lists, tables). This is
presentation only — the report's content is entirely the engine's own
output; nothing is computed here.
"""

import html as html_lib

from data_access import read_text, file_exists


def _render_markdown_lite(text):
    lines = text.split("\n")
    out = []
    in_list = False
    table_rows = []

    def flush_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    def flush_table():
        nonlocal table_rows
        if not table_rows:
            return
        header, _, *body = table_rows
        headers = [c.strip() for c in header.strip("|").split("|")]
        out.append("<table class='report-table'><thead><tr>")
        out.extend(f"<th>{html_lib.escape(h)}</th>" for h in headers)
        out.append("</tr></thead><tbody>")
        for row in body:
            cells = [c.strip() for c in row.strip("|").split("|")]
            out.append("<tr>" + "".join(f"<td>{html_lib.escape(c)}</td>" for c in cells) + "</tr>")
        out.append("</tbody></table>")
        table_rows = []

    def inline(s):
        s = html_lib.escape(s)
        s = _bold(s)
        return s

    def _bold(s):
        import re
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)

    for raw_line in lines:
        line = raw_line.rstrip()
        is_table_line = line.strip().startswith("|") and line.strip().endswith("|")

        if is_table_line:
            table_rows.append(line.strip())
            continue
        elif table_rows:
            flush_table()

        if line.startswith("### "):
            flush_list()
            out.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("## "):
            flush_list()
            out.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("# "):
            flush_list()
            out.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.strip().startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line.strip()[2:])}</li>")
        elif line.strip() == "":
            flush_list()
        else:
            flush_list()
            out.append(f"<p>{inline(line)}</p>")

    flush_list()
    flush_table()
    return "\n".join(out)


def get_context():
    raw = read_text("results/reconciliation_report.md")
    return {
        "report_found": file_exists("results/reconciliation_report.md"),
        "report_html": _render_markdown_lite(raw) if raw else None,
    }
