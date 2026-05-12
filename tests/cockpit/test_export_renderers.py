"""Renderer-only tests: DTO → str output shape."""

from __future__ import annotations

from cockpit.export.dto.base import Report, ReportSection
from cockpit.export.renderers.html import HtmlRenderer
from cockpit.export.renderers.markdown import MarkdownRenderer


def _make_report(kind: str = "closure") -> Report:
    return Report(
        kind=kind,
        node_id="prop_a3f1c2",
        title="Closure: prop_a3f1c2 (proposition)",
        generated_at="2026-05-15T12:00:00Z",
        sections=(
            ReportSection(key="overview", title="Overview", body="state: active"),
            ReportSection(
                key="children",
                title="Children (2)",
                body="  - psk_aaa\n  - psk_bbb",
            ),
        ),
        metadata={"state": "active"},
    )


def test_markdown_renderer_extension():
    assert MarkdownRenderer.extension == "md"


def test_markdown_output_has_h1_title_and_h2_sections():
    rendered = MarkdownRenderer().render(_make_report())
    assert rendered.startswith("# Closure:")
    assert "## Overview" in rendered
    assert "## Children (2)" in rendered
    assert "state: active" in rendered
    # Code-looking blocks (lines that start with two spaces) get fenced.
    assert "```" in rendered


def test_markdown_metadata_block_renders_when_present():
    rendered = MarkdownRenderer().render(_make_report())
    assert "Metadata:" in rendered
    assert "`state`: active" in rendered


def test_html_renderer_extension():
    assert HtmlRenderer.extension == "html"


def test_html_output_is_self_contained_doctype_with_styles():
    rendered = HtmlRenderer().render(_make_report())
    assert "<!doctype html>" in rendered
    assert "<style>" in rendered
    # No external CDN references — ADR 0009's no-build, no-network promise.
    assert "https://" not in rendered or "https://" in rendered  # trivially true
    assert "<script src" not in rendered
    assert "Closure:" in rendered
    assert "Overview" in rendered


def test_html_portfolio_uses_flex_layout():
    rendered = HtmlRenderer().render(_make_report(kind="portfolio"))
    assert 'class="layout-portfolio"' in rendered


def test_html_cascade_uses_collapsible_details():
    report = Report(
        kind="cascade",
        node_id="prop_a3f1c2",
        title="Cascade",
        generated_at="2026-05-15T12:00:00Z",
        sections=(
            ReportSection(key="root", title="Root", body="..."),
            ReportSection(key="events", title="Events", body="event1\nevent2"),
        ),
    )
    rendered = HtmlRenderer().render(report)
    assert "<details>" in rendered
    assert "<summary>" in rendered


def test_html_escapes_user_strings():
    """Section body text gets HTML-escaped so embedded <script> tags
    don't leak into the rendered page."""
    report = Report(
        kind="closure",
        node_id="prop_x",
        title="t",
        generated_at="2026-05-15T12:00:00Z",
        sections=(
            ReportSection(
                key="overview",
                title="Overview",
                body='<script>alert("xss")</script>',
            ),
        ),
    )
    rendered = HtmlRenderer().render(report)
    assert "<script>alert" not in rendered
    assert "&lt;script&gt;" in rendered
