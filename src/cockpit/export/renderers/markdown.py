"""Markdown renderer for export reports.

Output format:

    # <title>

    > generated at: <iso timestamp>
    > kind: <kind>  ·  node: <node_id>

    ## <section title>
    <section body>

    ## <next section title>
    ...

For PortfolioReport, each candidate is its own ``##`` section because
markdown has no native side-by-side primitive — the HTML renderer is
the right tool when the user wants the column layout.

The renderer keeps a small footprint on purpose: pure stdlib, no
external markdown libs, no syntax highlighting. The output should
render identically in any markdown viewer that supports CommonMark
basics (headings, blockquotes, code blocks).
"""

from __future__ import annotations

from cockpit.export.dto.base import Report


class MarkdownRenderer:
    extension = "md"

    def render(self, report: Report) -> str:
        parts: list[str] = [
            f"# {report.title}",
            "",
            f"> generated at: {report.generated_at}",
            f"> kind: `{report.kind}`  ·  node: `{report.node_id}`",
            "",
        ]
        for section in report.sections:
            parts.append(f"## {section.title}")
            parts.append("")
            parts.append(self._format_body(section.body))
            parts.append("")
        if report.metadata:
            parts.append("---")
            parts.append("")
            parts.append("Metadata:")
            parts.append("")
            for key in sorted(report.metadata):
                value = report.metadata[key]
                parts.append(f"- `{key}`: {value}")
            parts.append("")
        return "\n".join(parts).rstrip() + "\n"

    @staticmethod
    def _format_body(body: str) -> str:
        """Wrap multi-line section bodies in a fenced code block when they
        look code-shaped (multiple lines, leading whitespace, ASCII art).

        Plain prose passes through unchanged so headings and links keep
        their markdown formatting. The heuristic: if any line starts
        with 2+ spaces or a backtick / brace / bracket, treat the whole
        body as preformatted.
        """
        if not body:
            return ""
        looks_code = any(
            line.startswith(("  ", "\t", "`", "{", "[")) for line in body.splitlines()
        )
        if looks_code and "\n" in body:
            return f"```\n{body}\n```"
        return body
