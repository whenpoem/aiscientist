"""Event stream pane for the cockpit TUI."""

from __future__ import annotations

from datetime import datetime, timezone

from rich.text import Text
from textual.widgets import RichLog


class EventStreamPane(RichLog):
    """Streaming event log with filter and relative-time toggle support."""

    def __init__(self) -> None:
        super().__init__(max_lines=2000, wrap=False, highlight=False)
        self.id = "events-pane"
        self.classes = "pane"
        self.border_title = "3 Event Stream"
        self._rows: list[dict] = []
        self._filter_text = ""
        self._relative_timestamps = False

    def set_title(self, filter_text: str = "") -> None:
        suffix = f" (filter: {filter_text})" if filter_text else ""
        self.border_title = f"3 Event Stream{suffix}"

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
            self.write("No cockpit events yet.")
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
        line.append(f"{timestamp}  ", style="#6e7681")
        line.append(kind, style="bold #58a6ff")
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
        if kind == "note":
            return str(payload.get("text", ""))
        if kind == "snapshot_created":
            return f"{payload.get('snapshot_id', '-')} {payload.get('label', '')}".strip()
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
