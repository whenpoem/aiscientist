"""Colon-command parsing for :class:`cockpit.app.CockpitApp`.

This module owns command routing only. UI mutations remain explicit calls on
the app so Textual lifecycle and persistence stay with the application class.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from textual.css.query import NoMatches

from . import data
from .diagnostics import get_logger, reset_health
from .i18n import SUPPORTED_LANGS, t
from .theme import theme_names

if TYPE_CHECKING:
    from .app import CockpitApp


_log = get_logger("command_handler")


def execute_command(app: CockpitApp, command: str) -> None:
    """Parse and execute one colon command against ``app``."""
    if not command:
        return
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        app.notify(t(app.lang, "command_parse_error", error=str(exc)), severity="warning")
        return
    if not parts:
        return
    op, *args = parts
    if op == "note":
        data.record_event("note", {"text": " ".join(args)}, source="cockpit_user")
    elif op in {"reject", "approve"}:
        target = args[0] if args else app.selected_node_id
        payload = " ".join(args[1:]) if len(args) > 1 else ""
        result = data.write_intervention(op, target, payload)
        app._track_intervention(result, op, target)  # noqa: SLF001
    elif op in {"halt", "redirect", "constrain"}:
        target = None if op == "halt" else app.selected_node_id
        result = data.write_intervention(op, target, " ".join(args))
        app._track_intervention(result, op, target)  # noqa: SLF001
    elif op == "pin" and len(args) >= 3:
        data.pin_metric_local(
            claim=args[1],
            value=args[2],
            session_id=args[0],
            source_command="cockpit",
            note="pinned from command mode",
        )
    elif op == "goto" and args:
        goto_node(app, args[0])
        return
    elif op == "pin":
        app.notify(t(app.lang, "command_pin_usage"), severity="warning")
        return
    elif op == "theme":
        if not args or args[0] not in theme_names():
            value = args[0] if args else ""
            app.notify(
                t(app.lang, "cmd_unknown_value", kind="theme", value=value),
                severity="warning",
            )
            return
        app._apply_theme(args[0], persist=True, notify=True)  # noqa: SLF001
        return
    elif op == "lang":
        if not args or args[0].lower() not in SUPPORTED_LANGS:
            value = args[0].lower() if args else ""
            app.notify(
                t(app.lang, "cmd_unknown_value", kind="lang", value=value),
                severity="warning",
            )
            return
        code = args[0].lower()
        if code != app.lang:
            app.lang = code
            app._apply_language()  # noqa: SLF001
            app.refresh_state(include_events=True)
            app.notify(t(app.lang, "language_notice"))
            app._persist_settings()  # noqa: SLF001
        return
    elif op == "focus":
        app._toggle_focus_impl()  # noqa: SLF001
        return
    elif op == "health":
        reset_health()
        app.notify(t(app.lang, "cmd_health_cleared"))
        return
    elif op == "timeline":
        _toggle_timeline(app, args)
        return
    else:
        app.notify(t(app.lang, "command_unknown", command=op), severity="warning")
        return
    app.refresh_state(include_events=True)


def _toggle_timeline(app: CockpitApp, args: list[str]) -> None:
    try:
        pane = app.timeline_pane
    except NoMatches:  # pragma: no cover - defensive
        return
    if args and args[0].lower() in {"on", "1", "show", "true"}:
        target = True
    elif args and args[0].lower() in {"off", "0", "hide", "false"}:
        target = False
    else:
        target = not pane.is_visible
    pane.set_visible(target)
    if target:
        try:
            pane.set_events(data.fetch_new_events(0, limit=200))
        except Exception:  # pragma: no cover - defensive
            _log.exception(":timeline fetch_events failed")
    app.notify(t(app.lang, "timeline_on" if target else "timeline_off"))


def goto_node(app: CockpitApp, target: str) -> None:
    """Jump to an exact node id or unique prefix without querying SQLite."""
    if not target:
        return
    nodes = app.graph.nodes
    if target in nodes:
        match = target
    else:
        candidates = [node_id for node_id in nodes if node_id.startswith(target)]
        if len(candidates) == 1:
            match = candidates[0]
        elif len(candidates) > 1:
            preview = ", ".join(candidates[:3])
            more = "" if len(candidates) <= 3 else f" (+{len(candidates) - 3})"
            app.notify(
                t(app.lang, "goto_ambiguous", target=target, preview=preview + more),
                severity="warning",
            )
            return
        else:
            app.notify(t(app.lang, "goto_not_found", target=target), severity="warning")
            return
    app._set_focus("tree")  # noqa: SLF001
    app.tree_pane.select_node_id(match)
    app.selected_node_id = match
    app._refresh_detail()  # noqa: SLF001


__all__ = ["execute_command", "goto_node"]
