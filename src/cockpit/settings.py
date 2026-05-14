"""Persistent cockpit user settings (~/.config/claudescientist/cockpit.toml).

A tiny TOML store for cockpit preferences that should outlive a single
session: chosen theme, language, layout, last focused pane, toggleable
display flags. Read uses ``tomllib`` from the stdlib (Python ≥ 3.11);
write uses a hand-written serializer because ``tomllib`` is read-only and
we don't want a runtime dependency on ``tomli_w`` for six string/bool keys.

The file is forgiving on first launch — a missing file or unparseable TOML
returns the default settings without raising. The schema is versioned so
future additions can migrate cleanly.

The path is overridable via the ``RESEARCH_AGENT_COCKPIT_CONFIG`` env var
(used in tests to keep TMPDIR-isolated state).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

SCHEMA_VERSION = 1

_ENV_OVERRIDE = "RESEARCH_AGENT_COCKPIT_CONFIG"
_SPLASH_ENV = "RESEARCH_AGENT_COCKPIT_SPLASH"


def should_show_splash(settings: "CockpitSettings") -> bool:
    """Decide whether the cockpit should run the startup splash this launch.

    The env var ``RESEARCH_AGENT_COCKPIT_SPLASH`` overrides the persisted
    setting in either direction (``"0"``/``"false"``/``"no"``/``"off"`` →
    disabled; ``"1"``/``"true"``/``"yes"``/``"on"`` → enabled). When the
    var is unset, the saved ``splash_animation`` flag wins.

    Centralising this lets ``conftest.py`` flip splash off for the whole
    test suite by setting the env var, while real launches stay on.
    """
    raw = os.environ.get(_SPLASH_ENV)
    if raw is not None:
        lowered = raw.strip().lower()
        if lowered in {"0", "false", "no", "off", ""}:
            return False
        if lowered in {"1", "true", "yes", "on"}:
            return True
        # Unparseable env value: fall back to the saved setting rather than
        # silently picking a side.
    return bool(settings.splash_animation)


def default_config_path() -> Path:
    """Return ``~/.config/claudescientist/cockpit.toml`` (or the env override)."""
    override = os.environ.get(_ENV_OVERRIDE)
    if override:
        return Path(override)
    if os.name == "nt":
        # Honor APPDATA on Windows so the file lives next to other Claude
        # tooling state instead of in the home directory root.
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "claudescientist" / "cockpit.toml"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "claudescientist" / "cockpit.toml"


@dataclass
class CockpitSettings:
    """User-tunable cockpit preferences."""

    schema_version: int = SCHEMA_VERSION
    theme: str = "claude-warm-dark"
    lang: str = "en"
    layout_preset: str = "wide"  # "wide" | "narrow" | "focus"
    focused_pane: str = "tree"
    relative_timestamps: bool = False
    show_refuted: bool = False
    reduced_motion: bool = False
    # v4.1.0a4 additions: per-pane display preferences. event_wrap controls
    # whether the event RichLog soft-wraps long payloads (True = readable
    # default, False = legacy single-line). tree_compact strips BT/Elo from
    # tree labels so node text gets the column width — power users can flip
    # back with `i`. wide_subpreset is a -1/0/+1 nudge on the wide-layout
    # tree column ratio: 0 keeps the v4.1.0a0 default (1:2:2), -1 narrows
    # the tree (1:2.5:2.5) for terminals where node text is short, +1
    # widens it (1.5:2:2) for projects with long hypothesis statements.
    event_wrap: bool = True
    tree_compact: bool = True
    wide_subpreset: int = 0
    # v4.1.0a6 addition: opt-out for the startup splash. Default ON because
    # the splash does double duty as launch theatre AND as a perceptual buffer
    # for the ~200-800ms it takes to fetch graph + events on cold start. Power
    # users who want straight-to-main can flip this off via the cockpit
    # settings file. Tests force-disable through RESEARCH_AGENT_COCKPIT_SPLASH.
    splash_animation: bool = True
    # v4.2.0a1 addition: per-section collapsed state for the detail pane.
    # Keys match SECTION_KEYS in cockpit.details; values are True when
    # the user has the section collapsed. Absent keys fall back to the
    # section's default_open setting on first render.
    detail_section_collapsed: dict = field(default_factory=dict)
    # v4.2.0a3 addition: True once the cold-start Welcome screen has
    # been dismissed at least once. The cockpit only re-shows it when
    # state.db is empty AND this flag is False, so deleting state.db
    # to start over also brings Welcome back — matching the user's
    # mental model of "fresh slate".
    welcome_shown: bool = False
    # v5.0 additions (Activity Streaming): phase_strip_visible toggles
    # the top phase strip (key ``P``); animations_enabled toggles
    # spinners / flashes / transitions on the activity pane (key ``m``)
    # for SSH / tmux / screen-reader users. Both default ON for the
    # vibecoding-style monitoring experience; the cockpit falls back
    # cleanly when either is False.
    phase_strip_visible: bool = True
    animations_enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "CockpitSettings":
        """Build from a parsed TOML dict, ignoring unknown keys.

        Coerces values to the declared field type. Anything that can't be
        coerced (e.g. ``theme = 42`` from a hand-edited TOML) silently falls
        back to the field's default. The cockpit must boot even if the
        config file has been mangled — broken settings should never block
        the UI.
        """
        kwargs: dict[str, object] = {}
        valid = {f.name: f.type for f in fields(cls)}
        for key, raw in data.items():
            if key not in valid:
                continue
            coerced = _coerce_value(valid[key], raw)
            if coerced is _SENTINEL:
                continue  # leave the field at its default
            kwargs[key] = coerced
        try:
            return cls(**kwargs)  # type: ignore[arg-type]
        except TypeError:
            return cls()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def load_settings(path: Path | None = None) -> CockpitSettings:
    """Read settings from disk. Returns defaults on any failure."""
    target = path or default_config_path()
    try:
        raw = target.read_bytes()
    except OSError:
        return CockpitSettings()
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        return CockpitSettings()
    if not isinstance(data, dict):
        return CockpitSettings()
    return CockpitSettings.from_dict(data)


def save_settings(settings: CockpitSettings, path: Path | None = None) -> Path:
    """Write settings to disk in TOML format. Creates parent dir if missing.

    Returns the path written so callers (or tests) can confirm location.
    Failures (read-only filesystem, etc.) raise ``OSError`` — callers may
    swallow them; the cockpit still works without persistence.
    """
    target = path or default_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _serialize_toml(settings.to_dict())
    target.write_text(payload, encoding="utf-8")
    return target


def _serialize_toml(data: dict[str, object]) -> str:
    """Minimal TOML emitter for primitives we use (str, int, float, bool).

    Keeps a stable key order so diffs stay readable when the file is checked
    into a dotfile repo.
    """
    lines = ["# claudescientist cockpit user settings — managed by the TUI.", ""]
    for key in sorted(data.keys()):
        lines.append(f"{key} = {_render_value(data[key])}")
    return "\n".join(lines) + "\n"


def _render_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, dict):
        # Inline TOML table: { key = value, key = value }. We use this
        # rather than [table] headers so the file stays readable as one
        # key-per-line and the cockpit's empty-dict default round-trips
        # to literal `{}` without a stray section divider.
        parts: list[str] = []
        for key in sorted(value.keys()):
            if not isinstance(key, str):
                continue
            parts.append(f"{key} = {_render_value(value[key])}")
        return "{ " + ", ".join(parts) + " }" if parts else "{}"
    raise TypeError(f"Unsupported TOML value type: {type(value)!r}")


# Sentinel used by _coerce_value to mean "skip this key, keep the default".
# Distinct from None so that fields whose default IS None remain reachable.
_SENTINEL = object()


def _coerce_value(declared_type, raw):
    """Coerce a TOML value to the declared dataclass field type.

    The dataclass ``fields()`` API returns the field's annotation as a
    string (e.g. ``"str"``) under PEP 563. We compare against the string
    form rather than the resolved type to avoid importing ``typing`` and
    handling generic origins for our six simple field types.

    Returns ``_SENTINEL`` if coercion is impossible (caller should skip).
    """
    type_name = declared_type if isinstance(declared_type, str) else getattr(
        declared_type, "__name__", str(declared_type)
    )
    if type_name == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        if isinstance(raw, str):
            lowered = raw.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True
            if lowered in {"false", "0", "no", "off"}:
                return False
        return _SENTINEL
    if type_name == "int":
        if isinstance(raw, bool):
            # bool is an int subclass, but we want True→1 only when the
            # field really is int (it's not — schema_version is the only
            # int field and a bool there would be silly). Reject.
            return _SENTINEL
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str):
            try:
                return int(raw.strip())
            except ValueError:
                return _SENTINEL
        return _SENTINEL
    if type_name == "str":
        if isinstance(raw, str):
            return raw
        # Reject non-strings rather than coerce (e.g. theme=42 should not
        # become "42" — that yields a non-existent theme name and an
        # incorrect i18n lookup downstream).
        return _SENTINEL
    if type_name == "dict":
        if isinstance(raw, dict):
            # Tolerate only flat str→bool dicts (the shape v4.2 actually
            # writes). Anything else gets dropped on the floor; the
            # cockpit recovers by treating the section as fresh.
            cleaned: dict[str, bool] = {}
            for key, value in raw.items():
                if isinstance(key, str) and isinstance(value, bool):
                    cleaned[key] = value
            return cleaned
        return _SENTINEL
    # Unknown declared type — pass through unchanged.
    return raw
