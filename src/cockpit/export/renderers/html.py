"""Self-contained HTML renderer for export reports.

Output is a single ``.html`` file with inline ``<style>`` — no CDN
links, no external JS, no build step. Opens with ``os.startfile`` /
``open`` / ``xdg-open`` against the user's default browser.

Three layout shapes:

- ``portfolio``: candidates render side-by-side in a flex row that
  wraps at the viewport width. Lets the reviewer scan competing
  proof skeletons visually instead of scrolling through one
  long sequence.
- ``cascade``: sections nest inside collapsible ``<details>`` blocks.
  The chronological event list is the bulk of the content; the
  toggle keeps less-interesting events folded by default.
- everything else: vertical stack of sections.

The CSS is intentionally minimal — typography over chrome. The page
should be readable in printer paper as well as Firefox.
"""

from __future__ import annotations

import html as _html

from cockpit.export.dto.base import Report

_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>{css}</style>
</head>
<body>
  <header>
    <h1>{title}</h1>
    <p class="meta">
      <span><strong>kind:</strong> <code>{kind}</code></span>
      <span><strong>node:</strong> <code>{node_id}</code></span>
      <span><strong>generated at:</strong> {generated_at}</span>
    </p>
  </header>
  <main class="{main_class}">
{body}
  </main>
{metadata_block}
</body>
</html>
"""

_BASE_CSS = """
  :root {
    color-scheme: light dark;
    --bg: #fafafa;
    --fg: #1a1a1a;
    --muted: #666;
    --border: #d8d8d8;
    --accent: #d97757;
    --code-bg: #f0eee9;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #14110f;
      --fg: #f0ece6;
      --muted: #a99e8c;
      --border: #2a251e;
      --code-bg: #1e1a16;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--fg);
    font-family: ui-sans-serif, system-ui, -apple-system,
      BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 15px;
    line-height: 1.55;
  }
  header, main, footer { padding: 1.5rem 2rem; max-width: 100rem; margin: 0 auto; }
  h1 { margin: 0 0 0.4rem 0; font-size: 1.55rem; }
  .meta { color: var(--muted); font-size: 0.92rem; margin: 0 0 0.5rem 0; }
  .meta span { margin-right: 1.2rem; }
  code { background: var(--code-bg); padding: 0 0.3em; border-radius: 3px; font-size: 0.92em; }
  pre {
    background: var(--code-bg);
    padding: 0.8rem 1rem;
    border-radius: 4px;
    overflow-x: auto;
    font-size: 0.9rem;
    line-height: 1.45;
  }
  section.report-section {
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 1rem 1.2rem;
    margin: 0 0 1rem 0;
    background: var(--bg);
  }
  section.report-section h2 {
    margin: 0 0 0.6rem 0;
    font-size: 1.05rem;
    color: var(--accent);
  }
  main.layout-portfolio {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
  }
  main.layout-portfolio > section.report-section { flex: 1 1 22rem; min-width: 22rem; }
  details { margin-bottom: 0.4rem; }
  details > summary { cursor: pointer; color: var(--accent); }
  footer { color: var(--muted); font-size: 0.85rem; border-top: 1px solid var(--border); }
"""


class HtmlRenderer:
    extension = "html"

    def render(self, report: Report) -> str:
        main_class = (
            "layout-portfolio" if report.kind == "portfolio" else "layout-stack"
        )
        body_chunks: list[str] = []
        for section in report.sections:
            body_chunks.append(self._render_section(section, report.kind))
        body = "\n".join(body_chunks)
        metadata_block = ""
        if report.metadata:
            rows = "\n".join(
                f"      <li><code>{_html.escape(str(key))}</code>: "
                f"{_html.escape(str(report.metadata[key]))}</li>"
                for key in sorted(report.metadata)
            )
            metadata_block = (
                "  <footer>\n"
                "    <h2>Metadata</h2>\n"
                f"    <ul>\n{rows}\n    </ul>\n"
                "  </footer>\n"
            )
        return _PAGE_TEMPLATE.format(
            title=_html.escape(report.title),
            kind=_html.escape(report.kind),
            node_id=_html.escape(report.node_id),
            generated_at=_html.escape(report.generated_at),
            css=_BASE_CSS,
            main_class=main_class,
            body=body,
            metadata_block=metadata_block,
        )

    @staticmethod
    def _render_section(section, kind: str) -> str:
        title_html = _html.escape(section.title)
        # Cascade events render as collapsible details blocks; everything
        # else stays open by default.
        if kind == "cascade" and section.key == "events":
            return (
                f'    <section class="report-section">\n'
                f"      <h2>{title_html}</h2>\n"
                f'      <details>\n'
                f"        <summary>Show events</summary>\n"
                f"        <pre>{_html.escape(section.body)}</pre>\n"
                f"      </details>\n"
                f"    </section>"
            )
        # Treat any body containing newlines as preformatted text.
        if "\n" in (section.body or ""):
            inner = f"<pre>{_html.escape(section.body)}</pre>"
        else:
            inner = f"<p>{_html.escape(section.body)}</p>" if section.body else ""
        return (
            f'    <section class="report-section">\n'
            f"      <h2>{title_html}</h2>\n"
            f"      {inner}\n"
            f"    </section>"
        )
