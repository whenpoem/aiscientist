"""Cockpit theme registry — Anthropic-aligned palette with multi-theme switch.

Four themes are registered with the running ``App``:

- ``claude-warm-dark``  — default; Anthropic warm orange (#d97757) on cocoa.
- ``claude-warm-light`` — same hue family inverted for bright rooms.
- ``claude-cool-dark``  — preserves the prior GitHub-dark feel for users on
  old terminals or who prefer the familiar accent.
- ``claude-high-contrast`` — pure black/white + saturated accents for
  accessibility (WCAG AAA).

Tokens follow Textual's standard slots (``primary``, ``surface``, ...) plus
custom ``variables`` for cockpit-specific roles (kind colors, foreground
tiers, structural rules).
"""

from __future__ import annotations

from textual.theme import Theme

# ---------------------------------------------------------------------------
# claude-warm-dark — the new default. Cocoa background + Anthropic warm
# orange accent + sage/sky secondaries. Designed to harmonize with the
# Anthropic brand while staying readable on dark terminals.
# ---------------------------------------------------------------------------

WARM_DARK = Theme(
    name="claude-warm-dark",
    primary="#d97757",
    secondary="#6a9bcc",
    accent="#d97757",
    background="#1a1612",
    surface="#241e1a",
    panel="#2e2722",
    boost="#3a322c",
    foreground="#e8e2d8",
    success="#788c5d",
    warning="#e3b341",
    error="#cf6679",
    dark=True,
    variables={
        "tertiary": "#788c5d",
        "foreground-muted": "#a89e8e",
        "foreground-subtle": "#766c5e",
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
        # Phase B: severity is decoupled from primary/warning/error so a
        # ``medium``-severity card border no longer shares its color
        # with the active-pane highlight (``border-active``). The ramp
        # walks from cool gray (low) through amber (medium/high) to a
        # warmer red than `error` for critical, so the eye reads
        # severity intensity independently of the cockpit's accent.
        "severity-critical": "#d35858",
        "severity-high": "#c89043",
        "severity-medium": "#b8843d",
        "severity-low": "#7a7264",
        "severity-info": "#a89e8e",
    },
)


WARM_LIGHT = Theme(
    name="claude-warm-light",
    primary="#c45a3a",
    secondary="#3a6a9c",
    accent="#c45a3a",
    background="#faf6f0",
    surface="#f0e8de",
    panel="#e8dccd",
    boost="#dccdb8",
    foreground="#2a2520",
    success="#5a6c45",
    warning="#a87928",
    error="#a04050",
    dark=False,
    variables={
        "tertiary": "#5a6c45",
        "foreground-muted": "#5e544a",
        "foreground-subtle": "#8a8074",
        "border": "#dccdb8",
        "border-active": "#c45a3a",
        "rule": "#dccdb8",
        "kind-question": "#3a6a9c",
        "kind-hypothesis": "#3a6a9c",
        "kind-experiment": "#a87928",
        "kind-evidence": "#5a6c45",
        "kind-conclusion": "#7c5ca8",
        "kind-proposition": "#c45a3a",
        "kind-proof-skeleton": "#a04830",
        "kind-proof-snippet": "#7e3820",
        "kind-refuted": "#a04050",
        "severity-critical": "#a04050",
        "severity-high": "#a87928",
        "severity-medium": "#8a6620",
        "severity-low": "#8a8074",
        "severity-info": "#5e544a",
    },
)


COOL_DARK = Theme(
    name="claude-cool-dark",
    primary="#58a6ff",
    secondary="#79c0ff",
    accent="#58a6ff",
    background="#0d1117",
    surface="#161b22",
    panel="#21262d",
    boost="#30363d",
    foreground="#c9d1d9",
    success="#3fb950",
    warning="#d29922",
    error="#f85149",
    dark=True,
    variables={
        "tertiary": "#3fb950",
        "foreground-muted": "#8b949e",
        "foreground-subtle": "#6e7681",
        "border": "#21262d",
        "border-active": "#58a6ff",
        "rule": "#21262d",
        "kind-question": "#79c0ff",
        "kind-hypothesis": "#58a6ff",
        "kind-experiment": "#d29922",
        "kind-evidence": "#3fb950",
        "kind-conclusion": "#bc8cff",
        "kind-proposition": "#e3b341",
        "kind-proof-skeleton": "#d29922",
        "kind-proof-snippet": "#a98012",
        "kind-refuted": "#f85149",
        "severity-critical": "#f85149",
        "severity-high": "#d29922",
        "severity-medium": "#a98012",
        "severity-low": "#8b949e",
        "severity-info": "#6e7681",
    },
)


HIGH_CONTRAST = Theme(
    name="claude-high-contrast",
    primary="#ff8800",
    secondary="#00aaff",
    accent="#ff8800",
    background="#000000",
    surface="#0a0a0a",
    panel="#141414",
    boost="#1f1f1f",
    foreground="#ffffff",
    success="#00ff00",
    warning="#ffff00",
    error="#ff0000",
    dark=True,
    variables={
        "tertiary": "#00ff00",
        "foreground-muted": "#cccccc",
        "foreground-subtle": "#999999",
        "border": "#666666",
        "border-active": "#ff8800",
        "rule": "#444444",
        "kind-question": "#00aaff",
        "kind-hypothesis": "#00aaff",
        "kind-experiment": "#ffff00",
        "kind-evidence": "#00ff00",
        "kind-conclusion": "#ff00ff",
        "kind-proposition": "#ff8800",
        "kind-proof-skeleton": "#ff8800",
        "kind-proof-snippet": "#cc6600",
        "kind-refuted": "#ff0000",
        # High-contrast severity: NASA-control-room amber/red rather
        # than fully saturated RGB. AAA contrast against #000 background
        # without the LCD edge-chromatic-aberration of pure #00ff00.
        "severity-critical": "#ff5050",
        "severity-high": "#ffb000",
        "severity-medium": "#ff8800",
        "severity-low": "#cccccc",
        "severity-info": "#999999",
    },
)


ALL_THEMES: tuple[Theme, ...] = (WARM_DARK, WARM_LIGHT, COOL_DARK, HIGH_CONTRAST)


def theme_names() -> list[str]:
    """Return the cycle order of registered theme names."""
    return [theme.name for theme in ALL_THEMES]


def next_theme(current: str) -> str:
    """Return the next theme in the cycle. Falls back to the default if the
    current name is unknown."""
    names = theme_names()
    if current not in names:
        return names[0]
    idx = names.index(current)
    return names[(idx + 1) % len(names)]


def default_theme_name() -> str:
    return WARM_DARK.name


def get_theme(name: str) -> Theme | None:
    """Look up a registered theme by name."""
    for theme in ALL_THEMES:
        if theme.name == name:
            return theme
    return None
