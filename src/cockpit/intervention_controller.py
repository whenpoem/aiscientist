"""Cockpit intervention queue bookkeeping and honest user feedback."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import data
from .i18n import t

if TYPE_CHECKING:
    from .app import CockpitApp


def queue_intervention(app: CockpitApp, kind: str) -> None:
    """Queue one selected-node intervention and refresh visible state."""
    node_id = app._require_selected_node()  # noqa: SLF001
    if node_id is None:
        return
    result = data.write_intervention(kind, node_id, "")
    track_intervention(app, result, kind, node_id)
    app._flash_intervention()  # noqa: SLF001
    app.refresh_state(include_events=True)


def track_intervention(
    app: CockpitApp,
    result: dict | None,
    kind: str,
    target: str | None,
) -> None:
    """Update the undo pointer and confirm queueing without claiming delivery."""
    if result and "intervention_id" in result:
        app._last_intervention_id = int(result["intervention_id"])  # noqa: SLF001
        app._last_intervention_kind = kind  # noqa: SLF001
        app._last_intervention_target = target  # noqa: SLF001
    else:
        app._last_intervention_id = None  # noqa: SLF001
        app._last_intervention_kind = None  # noqa: SLF001
        app._last_intervention_target = None  # noqa: SLF001
    notify_intervention_queued(app, kind, target)


def notify_intervention_queued(
    app: CockpitApp, kind: str, target: str | None
) -> None:
    """Report enqueue status; hook delivery occurs on a later lifecycle event."""
    if target:
        message = t(
            app.lang,
            "intervention_queued",
            kind=kind,
            target=short_node_label(target),
        )
    else:
        message = t(app.lang, "intervention_queued_no_target", kind=kind)
    if app._last_intervention_id is not None:  # noqa: SLF001
        message = message + " - " + t(app.lang, "intervention_undo_hint")
    app.notify(message)


def short_node_label(target: str) -> str:
    """Compact a node id for intervention toast text."""
    if "_" not in target:
        return target[:10]
    prefix, suffix = target.split("_", 1)
    return f"{prefix}_{suffix[:4]}"


__all__ = [
    "notify_intervention_queued",
    "queue_intervention",
    "short_node_label",
    "track_intervention",
]
