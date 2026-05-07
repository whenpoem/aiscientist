"""Tests for cockpit settings persistence (TOML round-trip + edge cases)."""

from __future__ import annotations

from pathlib import Path

from cockpit.settings import (
    SCHEMA_VERSION,
    CockpitSettings,
    default_config_path,
    load_settings,
    save_settings,
)


def test_default_settings_match_warm_dark_baseline():
    settings = CockpitSettings()
    assert settings.theme == "claude-warm-dark"
    assert settings.lang == "en"
    assert settings.layout_preset == "wide"
    assert settings.focused_pane == "tree"
    assert settings.relative_timestamps is False
    assert settings.show_refuted is False
    assert settings.reduced_motion is False
    assert settings.schema_version == SCHEMA_VERSION


def test_round_trip_preserves_user_choices(tmp_path: Path):
    target = tmp_path / "cockpit.toml"
    original = CockpitSettings(
        theme="claude-cool-dark",
        lang="zh",
        layout_preset="focus",
        focused_pane="events",
        relative_timestamps=True,
        show_refuted=True,
        reduced_motion=True,
    )
    save_settings(original, target)
    loaded = load_settings(target)
    assert loaded.theme == "claude-cool-dark"
    assert loaded.lang == "zh"
    assert loaded.layout_preset == "focus"
    assert loaded.focused_pane == "events"
    assert loaded.relative_timestamps is True
    assert loaded.show_refuted is True
    assert loaded.reduced_motion is True


def test_load_returns_defaults_when_file_missing(tmp_path: Path):
    target = tmp_path / "does-not-exist.toml"
    loaded = load_settings(target)
    assert loaded.theme == "claude-warm-dark"
    assert loaded.lang == "en"


def test_load_tolerates_corrupt_toml(tmp_path: Path):
    target = tmp_path / "broken.toml"
    target.write_text("this is not = valid [[ toml", encoding="utf-8")
    loaded = load_settings(target)
    # Failure path returns defaults rather than raising.
    assert loaded.theme == "claude-warm-dark"


def test_load_ignores_unknown_keys(tmp_path: Path):
    target = tmp_path / "future.toml"
    target.write_text(
        'theme = "claude-cool-dark"\n'
        'lang = "zh"\n'
        'future_field = "ignored"\n',
        encoding="utf-8",
    )
    loaded = load_settings(target)
    assert loaded.theme == "claude-cool-dark"
    assert loaded.lang == "zh"


def test_save_creates_parent_directories(tmp_path: Path):
    nested = tmp_path / "deeper" / "still" / "cockpit.toml"
    save_settings(CockpitSettings(), nested)
    assert nested.exists()
    text = nested.read_text(encoding="utf-8")
    assert "schema_version = 1" in text
    assert 'theme = "claude-warm-dark"' in text


def test_save_escapes_quotes_in_strings(tmp_path: Path):
    target = tmp_path / "quoted.toml"
    settings = CockpitSettings(theme='odd"name')
    save_settings(settings, target)
    text = target.read_text(encoding="utf-8")
    assert 'theme = "odd\\"name"' in text


def test_default_config_path_honors_env_override(monkeypatch, tmp_path: Path):
    target = tmp_path / "override" / "cockpit.toml"
    monkeypatch.setenv("RESEARCH_AGENT_COCKPIT_CONFIG", str(target))
    assert default_config_path() == target


def test_default_config_path_returns_namespaced_path(monkeypatch):
    """Without env override, the path lives under a `claudescientist/` dir
    on every supported platform. We don't try to spoof os.name (which
    breaks pytest internals on Windows) — the per-platform branch is
    well-tested by simple visual inspection of the source."""
    monkeypatch.delenv("RESEARCH_AGENT_COCKPIT_CONFIG", raising=False)
    path = default_config_path()
    assert "claudescientist" in path.as_posix()
    assert path.name == "cockpit.toml"
