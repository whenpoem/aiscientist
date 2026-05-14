"""Runtime accessor for cockpit theme color tokens.

Widgets that build Rich ``Text`` styles dynamically (tree pane prefixes,
detail pane headings, event-stream rows, status-bar segments) should resolve
their colors via :func:`color` instead of hard-coding hex literals. The
function reads from a module-level dict that the App keeps up to date via
:func:`update_theme_vars` whenever the active theme changes.

Why a module-level dict and not ``self.app.current_theme``?
- It works the same way before the App has booted (unit tests instantiating
  widgets directly without a running app context).
- It lets non-widget helpers (event summarizers, formatters) resolve colors
  without needing an app handle.
- It dodges the slight version drift between Textual releases on how
  ``current_theme`` is exposed.

The fallback dict mirrors ``claude-warm-dark`` so anything rendered before
the App's ``on_mount`` finishes still looks coherent.
"""

from __future__ import annotations

# Fallback palette = claude-warm-dark. Used when no App is running yet and
# kept as a backstop for any token a custom user theme forgets to define.
_FALLBACKS: dict[str, str] = {
    "primary": "#d97757",
    "secondary": "#6a9bcc",
    "tertiary": "#788c5d",
    "accent": "#d97757",
    "background": "#1a1612",
    "surface": "#241e1a",
    "panel": "#2e2722",
    "boost": "#3a322c",
    "foreground": "#e8e2d8",
    "foreground-muted": "#a89e8e",
    "foreground-subtle": "#766c5e",
    "warning": "#e3b341",
    "error": "#cf6679",
    "success": "#788c5d",
    "border": "#3a322c",
    "border-active": "#d97757",
    "rule": "#3a322c",
    "kind-question": "#9bb8d9",
    "kind-hypothesis": "#6a9bcc",
    "kind-experiment": "#e3b341",
    "kind-evidence": "#788c5d",
    "kind-conclusion": "#bc8cff",
    "kind-proposition": "#d97757",
    "kind-proof-skeleton": "#c45a3a",
    "kind-proof-snippet": "#a04830",
    "kind-refuted": "#cf6679",
    # Activity card severity bands. Phase B: decoupled from
    # primary/warning/error so a medium-severity card border no longer
    # collides with the active-pane highlight (``border-active``). The
    # ramp walks cool-gray → amber → muted red, independent of the
    # cockpit's primary accent. Glyphs in activity.py (█▓▒░ ) carry
    # the same intensity signal as a fill-density gradient so users
    # who cannot rely on color (red-green colour-blindness) still get
    # the loudness cue.
    "severity-critical": "#d35858",
    "severity-high": "#c89043",
    "severity-medium": "#b8843d",
    "severity-low": "#7a7264",
    "severity-info": "#a89e8e",
}

_CURRENT_VARS: dict[str, str] = dict(_FALLBACKS)

# Mapping from token name to the corresponding Theme attribute. Tokens not
# listed here are read from ``Theme.variables`` only.
_BUILTIN_ATTRS = {
    "primary": "primary",
    "secondary": "secondary",
    "accent": "accent",
    "background": "background",
    "surface": "surface",
    "panel": "panel",
    "boost": "boost",
    "foreground": "foreground",
    "warning": "warning",
    "error": "error",
    "success": "success",
}


def update_theme_vars(theme) -> None:
    """Refresh the in-process color table from a Textual ``Theme`` instance.

    Called by the App whenever ``self.theme`` changes. Always starts from the
    static fallbacks so a custom theme that omits a variable still resolves
    cleanly.
    """
    global _CURRENT_VARS
    new = dict(_FALLBACKS)
    for token, attr in _BUILTIN_ATTRS.items():
        val = getattr(theme, attr, None)
        if val:
            new[token] = str(val)
    variables = getattr(theme, "variables", None)
    if variables:
        for key, val in variables.items():
            if val:
                new[key] = str(val)
    _CURRENT_VARS = new


def reset_theme_vars() -> None:
    """Restore fallback values. Intended for tests."""
    global _CURRENT_VARS
    _CURRENT_VARS = dict(_FALLBACKS)


def color(token: str) -> str:
    """Resolve a semantic token to a Rich-compatible color string.

    Always returns a non-empty string (falls back to the foreground color if
    the token is unknown).
    """
    return _CURRENT_VARS.get(token, _FALLBACKS.get(token, "#c9d1d9"))


def style(token: str, *, bold: bool = False, dim: bool = False, strike: bool = False) -> str:
    """Compose a Rich style string from a foreground token + optional modifiers.

    Examples
    --------
    >>> style("primary", bold=True)  # doctest: +SKIP
    'bold #d97757'
    >>> style("foreground-muted", dim=True)  # doctest: +SKIP
    'dim #a89e8e'
    """
    parts: list[str] = []
    if bold:
        parts.append("bold")
    if dim:
        parts.append("dim")
    if strike:
        parts.append("strike")
    parts.append(color(token))
    return " ".join(parts)


def kind_color(kind: str) -> str:
    """Resolve the color for a graph node kind (one of the ``kind-*`` tokens)."""
    return color(f"kind-{kind.replace('_', '-')}")
