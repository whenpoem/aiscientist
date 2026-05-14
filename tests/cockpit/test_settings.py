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


# ---------------------------------------------------------------------------
# Phase A: migration scaffold
# ---------------------------------------------------------------------------


def test_migrate_is_pass_through_for_current_schema(tmp_path: Path):
    """Phase A ships the migration scaffold as a near-noop. A dict whose
    schema_version already matches SCHEMA_VERSION should come back with
    the same shape (modulo schema_version being explicitly set)."""
    from cockpit.settings import SCHEMA_VERSION, migrate

    original = {
        "schema_version": SCHEMA_VERSION,
        "theme": "claude-cool-dark",
        "lang": "zh",
        "focused_pane": "events",  # still valid on-disk (app heals at runtime)
    }
    migrated = migrate(dict(original))
    assert migrated["schema_version"] == SCHEMA_VERSION
    assert migrated["theme"] == "claude-cool-dark"
    assert migrated["lang"] == "zh"
    assert migrated["focused_pane"] == "events"


def test_migrate_coerces_missing_schema_version(tmp_path: Path):
    from cockpit.settings import SCHEMA_VERSION, migrate

    migrated = migrate({"theme": "claude-warm-dark"})
    # Coerced up to the current version so a re-save will land the
    # right marker for future cockpits to read.
    assert migrated["schema_version"] == SCHEMA_VERSION


def test_migrate_future_version_logs_warning(monkeypatch, tmp_path: Path):
    """A file written by a newer cockpit must still load — but it should
    light up the HUD ⚠ chip so the user knows their config may be only
    partially honored."""
    from cockpit import diagnostics
    from cockpit.settings import migrate

    monkeypatch.setenv(
        "RESEARCH_AGENT_COCKPIT_CONFIG", str(tmp_path / "cockpit.toml")
    )
    diagnostics._INITIALIZED = False  # noqa: SLF001 - force re-init under tmp_path
    import logging as _logging

    for handler in list(_logging.getLogger("cockpit").handlers):
        _logging.getLogger("cockpit").removeHandler(handler)
    diagnostics.reset_health()

    migrated = migrate({"schema_version": 999, "theme": "claude-warm-dark"})
    # The future version marker is preserved so a subsequent newer
    # cockpit doesn't think we downgraded.
    assert migrated["schema_version"] == 999
    state = diagnostics.health_state()
    assert state["warnings"] == 1
    assert "newer" in state["last_message"].lower()


def test_load_settings_round_trips_focused_pane_events(tmp_path: Path):
    """Regression: the runtime ``events → activity`` heal lives in
    :class:`cockpit.app.CockpitApp`, NOT in the settings layer. The
    on-disk form must still preserve ``focused_pane = "events"`` so
    pre-v5 configs survive a load/save cycle without losing user intent.
    """
    target = tmp_path / "cockpit.toml"
    target.write_text(
        'theme = "claude-warm-dark"\nfocused_pane = "events"\n',
        encoding="utf-8",
    )
    loaded = load_settings(target)
    assert loaded.focused_pane == "events"
