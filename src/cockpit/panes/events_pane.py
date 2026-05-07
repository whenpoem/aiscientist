"""Event stream pane for the cockpit TUI."""

from __future__ import annotations

from datetime import datetime, timezone

from rich.text import Text
from textual.widgets import RichLog

from cockpit.i18n import t
from cockpit.theme import color
from cockpit.theme import style as theme_style


class EventStreamPane(RichLog):
    """Streaming event log with filter and relative-time toggle support."""

    def __init__(self) -> None:
        super().__init__(max_lines=2000, wrap=False, highlight=False)
        self.id = "events-pane"
        self.classes = "pane"
        self.lang = "en"
        self.border_title = t(self.lang, "events_title")
        self._rows: list[dict] = []
        self._filter_text = ""
        self._relative_timestamps = False

    def set_language(self, lang: str) -> None:
        self.lang = lang
        self.set_title(self._filter_text)
        self._rerender()

    def set_title(self, filter_text: str = "") -> None:
        suffix = (
            f" ({t(self.lang, 'filter_suffix', value=filter_text)})"
            if filter_text
            else ""
        )
        self.border_title = f"{t(self.lang, 'events_title')}{suffix}"

    def set_filter_text(self, filter_text: str) -> None:
        self._filter_text = filter_text.strip().lower()
        self.set_title(filter_text.strip())
        self._rerender()

    def set_relative_timestamps(self, enabled: bool) -> None:
        self._relative_timestamps = enabled
        self._rerender()

    def set_rows(self, rows: list[dict]) -> None:
        self._rows = list(rows)
        self._rerender()

    def append_rows(self, rows: list[dict]) -> None:
        if not rows:
            return
        self._rows.extend(rows)
        if self._filter_text:
            self._rerender()
            return
        for row in rows:
            self.write(self._render_row(row))

    def clear_visual(self) -> None:
        self.clear()

    def _rerender(self) -> None:
        self.clear()
        rendered = [
            row
            for row in self._rows
            if not self._filter_text or self._matches_filter(row)
        ]
        if not rendered:
            self.write(t(self.lang, "no_events"))
            return
        for row in rendered:
            self.write(self._render_row(row))

    def _matches_filter(self, row: dict) -> bool:
        haystack = f"{row.get('kind', '')} {row.get('payload', {})}".lower()
        return self._filter_text in haystack

    def _render_row(self, row: dict) -> Text:
        timestamp = self._format_timestamp(str(row.get("created_at", "")))
        kind = str(row.get("kind", "event"))
        summary = self._summarize(row)
        line = Text()
        line.append(f"{timestamp}  ", style=color("foreground-subtle"))
        # Proof-trunk events get the proof token color; everything else uses
        # the primary accent. This keeps the two trunks visually separable
        # at a glance.
        if kind.startswith("proof_") or kind.startswith("lean_"):
            line.append(kind, style=theme_style("kind-proposition", bold=True))
        else:
            line.append(kind, style=theme_style("primary", bold=True))
        line.append("  ")
        line.append(summary)
        return line

    def _summarize(self, row: dict) -> str:
        kind = str(row.get("kind", "event"))
        payload = row.get("payload") or {}
        if kind == "graph_delta":
            return (
                f"{payload.get('node_id', '-')} "
                f"{payload.get('kind', '')} {payload.get('text', '')}".strip()
            )
        if kind == "failure_added":
            return (
                f"{payload.get('failure_id', '-')} "
                f"{payload.get('trigger', '')} {payload.get('symptom', '')}"
            ).strip()
        if kind == "intervention":
            return (
                f"{payload.get('kind', '')} "
                f"{payload.get('target', '-') or '-'} {payload.get('payload', '')}"
            ).strip()
        if kind == "judgement_recorded":
            return (
                f"{payload.get('winner_node_id', '-')} beat "
                f"{payload.get('a_node_id', '-')} / {payload.get('b_node_id', '-')}"
            )
        if kind == "claim_pinned":
            return f"{payload.get('claim', '-')}={payload.get('value', '-')}"
        if kind == "seed_run_recorded":
            return (
                f"{payload.get('script_path', '-')} "
                f"{payload.get('verdict', '-')} mean={payload.get('mean_value', '-')}"
            )
        if kind == "heldout_query_reserved":
            return (
                f"{payload.get('dataset', '-')} "
                f"{payload.get('budget_used', '-')}/{payload.get('budget_total', '-')}"
            )
        if kind == "heldout_query_finished":
            return (
                f"{payload.get('query_id', '-')} {payload.get('status', '-')} "
                f"metric={payload.get('metric_value', '-')}"
            )
        if kind == "literature_ingested":
            return f"{payload.get('paper_id', '-')} {payload.get('title', '')}".strip()
        if kind == "note":
            return str(payload.get("text", ""))
        if kind == "snapshot_created":
            return f"{payload.get('snapshot_id', '-')} {payload.get('label', '')}".strip()
        # Proof trunk events (P5).
        if kind == "proof_corpus_ingested":
            return (
                f"{payload.get('problem_id', '-')} "
                f"lex={payload.get('n_lexical', 0)} "
                f"sem={payload.get('n_semantic', 0)}"
            ).strip()
        if kind == "proof_segmented":
            return (
                f"draft={payload.get('draft_id', '-')} "
                f"manifest={payload.get('manifest_id', '-')} "
                f"snippets={payload.get('snippet_count', 0)}"
            )
        if kind == "proof_diagnosis_recorded":
            flag = "FLAW" if payload.get("is_flawed") else "ok"
            return (
                f"manifest={payload.get('manifest_id', '-')} "
                f"snippet={payload.get('snippet_id', '-')} {flag}"
            )
        if kind == "proof_diagnosis_complete":
            return (
                f"manifest={payload.get('manifest_id', '-')} "
                f"status={payload.get('status', '-')} "
                f"flawed={payload.get('flawed_count', 0)}/"
                f"{payload.get('entry_count', 0)}"
            )
        if kind == "proof_correction_applied":
            return (
                f"old={payload.get('old_draft_id', '-')} -> "
                f"new={payload.get('new_draft_id', '-')}"
            )
        if kind in {"lean_proof_succeeded", "lean_proof_failed", "lean_proof_recorded"}:
            duration = payload.get("duration_sec")
            duration_str = f" {duration:.1f}s" if isinstance(duration, (int, float)) else ""
            return (
                f"prop={payload.get('proposition_id', '-')} "
                f"attempt={payload.get('attempt_id', '-')} "
                f"status={payload.get('status', kind)}"
                f"{duration_str}"
            )
        return str(payload)

    def _format_timestamp(self, raw: str) -> str:
        parsed = self._parse_timestamp(raw)
        if parsed is None:
            return raw[:8]
        if not self._relative_timestamps:
            return parsed.astimezone().strftime("%H:%M:%S")
        delta = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
        total = max(int(delta.total_seconds()), 0)
        minutes, seconds = divmod(total, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"-{hours}h {minutes:02d}m"
        if minutes:
            return f"-{minutes}m {seconds:02d}s"
        return f"-{seconds}s"

    @staticmethod
    def _parse_timestamp(raw: str) -> datetime | None:
        candidate = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            try:
                parsed = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
