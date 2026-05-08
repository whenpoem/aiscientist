"""Full-window DetailScreen used for drill-in from any list-style pane.

The user presses Enter on a row in the tree / events / tabs pane and the
App pushes a DetailScreen instance. The screen renders the current row's
title + body in the whole window, keeps the status and context bars
visible (so ambient awareness is not lost — see ADR 0003), and supports
``h`` / ``l`` to walk siblings without bouncing back to the main view.

Action keys (``y``/``n``/``r``/``c``/``m``/``p``/``H``) deliberately stay
bound on the App with ``priority=True``. They keep working inside the
DetailScreen as long as ``app.selected_node_id`` is kept in sync — which
this screen does on mount and on every navigation step. After an action
fires, the screen re-renders to reflect the change.
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Static

from cockpit.data import GraphSnapshot
from cockpit.details import event_detail_text, node_detail_text, short_id
from cockpit.i18n import t
from cockpit.theme import style as theme_style


@runtime_checkable
class DetailSource(Protocol):
    """Protocol for anything that can drive a DetailScreen.

    The DetailScreen calls ``current()`` to render the active item and
    ``move(delta)`` to advance/retreat among siblings. ``node_id()``
    returns the underlying graph node id when applicable so the App can
    sync ``selected_node_id`` and dispatch action keys correctly; sources
    that don't represent nodes return ``None``.
    """

    def current(self) -> tuple[str, Text | str]: ...

    def move(self, delta: int) -> bool: ...

    def node_id(self) -> str | None: ...

    def source_label(self) -> str: ...

    def set_language(self, lang: str) -> None: ...


class NodeDetailSource:
    """Walks the visible-node-id list around the currently selected one.

    The App passes the *visible* (post-filter, post-show-refuted) order
    so ``h`` / ``l`` mirror the order the user already saw in the tree.

    ``graph_provider`` is called on every ``current()`` so the rendered
    text reflects the freshest graph snapshot — important when an action
    key (y/n/r/c/m) inside the DetailScreen mutates state, the App's
    refresh_state() rebuilds ``self.graph``, and we want the screen to
    pick up the new node state on the next paint.
    """

    def __init__(
        self,
        graph_provider: Callable[[], GraphSnapshot],
        node_ids: list[str],
        current: str,
        lang: str,
    ) -> None:
        self._graph_provider = graph_provider
        self._ids = list(node_ids)
        try:
            self._idx = self._ids.index(current)
        except ValueError:
            # Edge case: the seed node was filtered out between push and
            # render (extremely unlikely under normal use, but defensive).
            self._idx = 0
        self._lang = lang

    def current(self) -> tuple[str, Text | str]:
        if not self._ids:
            return ("", t(self._lang, "no_hypotheses"))
        graph = self._graph_provider()
        return node_detail_text(graph, self._ids[self._idx], self._lang)

    def move(self, delta: int) -> bool:
        new_idx = self._idx + delta
        if 0 <= new_idx < len(self._ids):
            self._idx = new_idx
            return True
        return False

    def node_id(self) -> str | None:
        if not self._ids:
            return None
        return self._ids[self._idx]

    def source_label(self) -> str:
        return t(self._lang, "detail_source_tree")

    def set_language(self, lang: str) -> None:
        self._lang = lang


class TabRowDetailSource:
    """Walks the rows of the active tabs subtab. ``render_fn`` is the
    App's existing ``_row_detail`` so this source produces the same
    title/body the in-pane override used to."""

    def __init__(
        self,
        rows: list[dict],
        current_index: int,
        render_fn: Callable[[dict], tuple[str, str]],
        lang: str,
    ) -> None:
        self._rows = list(rows)
        self._idx = (
            current_index if 0 <= current_index < len(self._rows) else 0
        )
        self._render_fn = render_fn
        self._lang = lang

    def current(self) -> tuple[str, Text | str]:
        if not self._rows:
            return ("", "")
        title, body = self._render_fn(self._rows[self._idx])
        return (title, body)

    def move(self, delta: int) -> bool:
        new_idx = self._idx + delta
        if 0 <= new_idx < len(self._rows):
            self._idx = new_idx
            return True
        return False

    def node_id(self) -> str | None:
        return None

    def source_label(self) -> str:
        return t(self._lang, "detail_source_tabs")

    def set_language(self, lang: str) -> None:
        self._lang = lang


class EventDetailSource:
    """Walks recent events. ``rows`` is taken in newest-first order; we
    keep that order so ``l`` advances chronologically backward (older)
    and ``h`` walks toward newer events."""

    def __init__(self, rows: list[dict], current_index: int, lang: str) -> None:
        self._rows = list(rows)
        self._idx = (
            current_index if 0 <= current_index < len(self._rows) else 0
        )
        self._lang = lang

    def current(self) -> tuple[str, Text | str]:
        if not self._rows:
            return ("", t(self._lang, "no_events"))
        return event_detail_text(self._rows[self._idx], self._lang)

    def move(self, delta: int) -> bool:
        new_idx = self._idx + delta
        if 0 <= new_idx < len(self._rows):
            self._idx = new_idx
            return True
        return False

    def node_id(self) -> str | None:
        return None

    def source_label(self) -> str:
        return t(self._lang, "detail_source_events")

    def set_language(self, lang: str) -> None:
        self._lang = lang


class DetailScreen(Screen[None]):
    """Full-window detail viewer pushed on Enter from list-style panes.

    Layout (top → bottom):
        breadcrumb  (1 line, dock=top)
        body        (VerticalScroll + Static, fills remaining)
        context     (1 line, dock=bottom — i18n hint)

    The App's StatusBar is NOT duplicated here on purpose: Textual screens
    each render independently, so re-using one widget across two screens
    requires moving it between mount points. Instead we show a compact
    breadcrumb on this screen ("Tree › H_a3f1") that tells the user where
    they are; the live event count / risk count remains one Esc away.
    """

    DEFAULT_CSS = """
    DetailScreen #detail-screen-breadcrumb {
        height: 1;
        padding: 0 2;
        background: $surface;
        color: $foreground;
    }
    DetailScreen #detail-screen-body-scroll {
        height: 1fr;
        padding: 1 2;
    }
    DetailScreen #detail-screen-context {
        height: 1;
        padding: 0 2;
        background: $surface;
        color: $foreground 70%;
    }
    """

    BINDINGS = [
        Binding("escape", "pop_detail", "Back", priority=True),
        Binding("q", "pop_detail", "Back", priority=True),
        # h / l walk siblings; arrow keys aliased so mouse-light users have
        # an alternative without learning vim notation.
        Binding("l", "next_sibling", "Next", priority=True),
        Binding("h", "prev_sibling", "Prev", priority=True),
        Binding("right", "next_sibling", show=False, priority=True),
        Binding("left", "prev_sibling", show=False, priority=True),
        # j / k scroll the body — Textual's VerticalScroll widget has its
        # own bindings but they require the scroller itself to be focused.
        # Routing through the screen lets the user scroll without tabbing
        # away from the (invisible) keyboard handler.
        Binding("j", "scroll_down", "Down", show=False, priority=True),
        Binding("k", "scroll_up", "Up", show=False, priority=True),
    ]

    def __init__(self, source: DetailSource, *, lang: str = "en") -> None:
        super().__init__()
        self._source = source
        self._lang = lang

    def compose(self) -> ComposeResult:
        yield Static("", id="detail-screen-breadcrumb")
        with VerticalScroll(id="detail-screen-body-scroll"):
            yield Static("", id="detail-screen-body")
        yield Static("", id="detail-screen-context")

    def on_mount(self) -> None:
        self._paint()

    # -- public surface ----------------------------------------------------

    def refresh_content(self) -> None:
        """Re-render after the underlying data may have changed (e.g. an
        action key fired and the App refreshed state). Idempotent."""
        self._paint()

    def set_language(self, lang: str) -> None:
        """Update screen chrome and source-owned text after App language changes."""
        self._lang = lang
        self._source.set_language(lang)
        if self.is_mounted:
            self._paint()

    # -- internals ---------------------------------------------------------

    def _paint(self) -> None:
        # Named `_paint` (not `_render`) on purpose: Textual's Widget base
        # class already defines `_render()` for its own rendering pipeline,
        # and overriding it accidentally returns None instead of a Visual,
        # which crashes the screen's render with a NoneType.render_strips
        # error. This bit us during the v4.1.0a4 stage 3 rollout.
        title, body = self._source.current()
        breadcrumb_text = t(
            self._lang,
            "detail_screen_breadcrumb",
            source=self._source.source_label(),
            title=title or "-",
        )
        self.query_one("#detail-screen-breadcrumb", Static).update(
            Text(breadcrumb_text, style=theme_style("primary", bold=True))
        )
        self.query_one("#detail-screen-body", Static).update(body)
        self.query_one("#detail-screen-context", Static).update(
            t(self._lang, "detail_screen_hint")
        )
        # Sync the App's selected_node_id so action keys (y/n/r/c/m/p/H)
        # target the currently-displayed node. Sources that aren't node-
        # backed (events / tab rows) leave the selection alone.
        nid = self._source.node_id()
        if nid is not None:
            try:
                self.app.selected_node_id = nid  # type: ignore[attr-defined]
            except AttributeError:  # pragma: no cover - defensive
                pass
        # Reset scroll position so the user always sees the start of the
        # new item rather than landing mid-scroll from the previous one.
        try:
            self.query_one(
                "#detail-screen-body-scroll", VerticalScroll
            ).scroll_home(animate=False)
        except Exception:  # pragma: no cover
            pass

    def action_pop_detail(self) -> None:
        # Carry the source's current node id back to the main screen's
        # tree cursor so the highlight follows the user's navigation
        # inside the drill-in. Without this, h/l on the DetailScreen can
        # land on H_5 but Esc returns the user to H_2 (the original
        # selection) — confusing, because the App's selected_node_id
        # is already H_5 and the detail pane reflects H_5 too.
        nid = self._source.node_id()
        if nid is not None:
            try:
                self.app.tree_pane.select_node_id(nid)  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover - defensive
                pass
        self.app.pop_screen()

    def action_next_sibling(self) -> None:
        if self._source.move(1):
            self._paint()
        else:
            self.app.notify(t(self._lang, "detail_screen_at_last"))

    def action_prev_sibling(self) -> None:
        if self._source.move(-1):
            self._paint()
        else:
            self.app.notify(t(self._lang, "detail_screen_at_first"))

    def action_scroll_down(self) -> None:
        try:
            scroll = self.query_one(
                "#detail-screen-body-scroll", VerticalScroll
            )
            scroll.scroll_down(animate=False)
        except Exception:  # pragma: no cover
            pass

    def action_scroll_up(self) -> None:
        try:
            scroll = self.query_one(
                "#detail-screen-body-scroll", VerticalScroll
            )
            scroll.scroll_up(animate=False)
        except Exception:  # pragma: no cover
            pass


__all__ = [
    "DetailScreen",
    "DetailSource",
    "NodeDetailSource",
    "EventDetailSource",
    "TabRowDetailSource",
    "short_id",
]
