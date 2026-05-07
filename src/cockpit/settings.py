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
from dataclasses import asdict, dataclass, fields
from pathlib import Path

SCHEMA_VERSION = 1

_ENV_OVERRIDE = "RESEARCH_AGENT_COCKPIT_CONFIG"


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

    @classmethod
    def from_dict(cls, data: dict) -> "CockpitSettings":
        """Build from a parsed TOML dict, ignoring unknown keys.

        Treats type mismatches as 'use default' rather than raising — the
        cockpit must boot even if the config file has been hand-edited
        incorrectly.
        """
        kwargs: dict[str, object] = {}
        valid = {f.name: f.type for f in fields(cls)}
        for key, value in data.items():
            if key not in valid:
                continue
            kwargs[key] = value
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
    raise TypeError(f"Unsupported TOML value type: {type(value)!r}")
