"""Status and context bars for the Cockpit shell."""

from __future__ import annotations

from datetime import datetime, timezone

from textual.widgets import Static

from .bars import progress_bar
from .diagnostics import health_state
from .i18n import normalize_lang, t


def pane_label(lang: str, pane: str) -> str:
    table_en = {
        "tree": "Tree",
        "detail": "Detail",
        "activity": "Activity",
        "tabs": "Tabs",
        "events": "Audit log",
    }
    table_zh = {
        "tree": "假设树",
        "detail": "详情",
        "activity": "活动",
        "tabs": "表格",
        "events": "审计日志",
    }
    table = table_zh if str(lang).startswith("zh") else table_en
    return table.get(pane, pane or "?")


class StatusBar(Static):
    """Single-line status header."""

    def __init__(self, *, lang: str = "en", theme: str = "claude-warm-dark") -> None:
        super().__init__("")
        self.id = "status-bar"
        self.lang = normalize_lang(lang)
        self.theme_name = theme
        self.current_text = ""
        self._summary = {
            "active_hypotheses": 0,
            "refuted_nodes": 0,
            "pinned_claims": 0,
            "unverified_claims": 0,
            "heldout_budgets": [],
            "risks": 0,
            "latest_event_at": None,
        }
        self._clock = "--:--"
        self._heartbeat_phase = 0

    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick)
        self._refresh_display()

    def set_language(self, lang: str) -> None:
        self.lang = normalize_lang(lang)
        self._refresh_display()

    def set_theme_name(self, theme: str) -> None:
        self.theme_name = theme
        self._refresh_display()

    def set_summary(self, summary: dict) -> None:
        self._summary = dict(summary)
        self._refresh_display()

    def _tick(self) -> None:
        self._clock = datetime.now().strftime("%H:%M")
        self._heartbeat_phase = (self._heartbeat_phase + 1) & 0xFFFF
        self._refresh_display()

    def _refresh_display(self) -> None:
        compact_theme = self.theme_name.removeprefix("claude-") or self.theme_name
        try:
            hud_key = "hud_compact" if self.size.width < 100 else "hud"
        except Exception:  # pragma: no cover - pre-mount path
            hud_key = "hud"
        self.current_text = t(
            self.lang,
            hud_key,
            heartbeat=self._format_heartbeat(),
            app=t(self.lang, "app_name"),
            health=self._format_health(),
            focus_mode=self._format_focus_mode(),
            action_target=self._format_action_target(),
            active_hypotheses=self._summary.get("active_hypotheses", 0),
            refuted_nodes=self._summary.get("refuted_nodes", 0),
            pinned_claims=self._summary.get("pinned_claims", 0),
            unverified_claims=self._summary.get("unverified_claims", 0),
            heldout=self._format_heldout(),
            risks=self._summary.get("risks", 0),
            last_event=self._format_last_event(),
            theme=compact_theme,
            lang_code=self.lang.upper(),
            clock=self._clock,
        )
        self.update(self.current_text)

    def _format_heartbeat(self) -> str:
        raw = self._summary.get("latest_event_at")
        warm = False
        if raw:
            try:
                parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - parsed).total_seconds()
                warm = 0 <= age < 10
            except ValueError:
                warm = False
        if not warm:
            return "[$foreground-muted]○[/]"
        return "[$accent]●[/]" if self._heartbeat_phase & 1 else "[$foreground]●[/]"

    def _format_action_target(self) -> str:
        try:
            node_id = getattr(self.app, "selected_node_id", None)
        except Exception:  # pragma: no cover - app teardown edge
            return t(self.lang, "action_target_empty")
        if not node_id:
            return t(self.lang, "action_target_empty")
        return t(self.lang, "action_target", target=node_id)

    def _format_focus_mode(self) -> str:
        try:
            preset = self.app._settings.layout_preset  # type: ignore[attr-defined]
            focused = self.app.focused_pane  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - app teardown edge
            return t(self.lang, "focus_mode_off")
        if preset not in ("focus", "single"):
            return t(self.lang, "focus_mode_off")
        return t(self.lang, "focus_mode_on", pane=pane_label(self.lang, focused))

    def _format_health(self) -> str:
        try:
            state = health_state()
        except Exception:  # pragma: no cover - defensive diagnostics path
            return t(self.lang, "health_clean")
        total = int(state.get("errors", 0) or 0) + int(state.get("warnings", 0) or 0)
        if total <= 0:
            return t(self.lang, "health_clean")
        return t(self.lang, "health_warning", count=total)

    def _format_heldout(self) -> str:
        budgets = self._summary.get("heldout_budgets") or []
        if not budgets:
            return t(self.lang, "heldout_none")
        parts: list[str] = []
        for row in budgets[:2]:
            used = int(row.get("budget_used", 0) or 0)
            total = int(row.get("budget_total", 0) or 0)
            parts.append(
                f"{row.get('dataset', '-')} {progress_bar(used, total, width=6)} "
                f"{used}/{total}"
            )
        return ", ".join(parts)

    def _format_last_event(self) -> str:
        raw = self._summary.get("latest_event_at")
        if not raw:
            return f"○ {t(self.lang, 'last_never')}"
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return f"● {str(raw)[:8]}"
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        seconds = max(
            int((datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()),
            0,
        )
        dot = "●" if seconds < 2 else "○"
        if seconds < 5:
            return f"{dot} {t(self.lang, 'just_now')}"
        if seconds < 60:
            return f"{dot} {t(self.lang, 'seconds_ago', value=seconds)}"
        minutes = seconds // 60
        if minutes < 60:
            return f"{dot} {t(self.lang, 'minutes_ago', value=minutes)}"
        return f"{dot} {t(self.lang, 'hours_ago', value=minutes // 60)}"


class ContextBar(Static):
    """Localized one-line hint for the focused pane."""

    def __init__(self, *, lang: str = "en") -> None:
        super().__init__("")
        self.id = "context-bar"
        self.lang = normalize_lang(lang)
        self.pane = "tree"
        self.current_text = ""
        self.refresh_text()

    def set_language(self, lang: str) -> None:
        self.lang = normalize_lang(lang)
        self.refresh_text()

    def set_pane(self, pane: str) -> None:
        self.pane = pane
        self.refresh_text()

    def refresh_text(self) -> None:
        key = {
            "tree": "context_tree",
            "tabs": "context_tabs",
            "events": "context_events",
            "detail": "context_detail",
        }.get(self.pane, "context_tree")
        self.current_text = t(self.lang, key)
        self.update(self.current_text)


__all__ = ["ContextBar", "StatusBar", "pane_label"]
