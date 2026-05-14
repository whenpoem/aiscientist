"""Tests for the Phase-A cockpit diagnostics layer.

Covers:

- :func:`cockpit.diagnostics.default_log_path` resolution honors
  ``RESEARCH_AGENT_COCKPIT_LOG`` and ``RESEARCH_AGENT_COCKPIT_CONFIG``
  with the expected precedence (matches the settings module so a single
  env-var redirects both files into ``tmp_path``).
- :func:`get_logger` writes WARNING/ERROR messages to the rotating log
  file and bumps the health-state counters.
- :func:`reset_health` returns the counters to zero — the cockpit calls
  this on every ``CockpitApp.__init__`` so per-launch state stays clean.
- The cockpit's HUD ``⚠`` chip only appears once the diagnostics module
  has actually logged a warning (no false positives on a clean launch).
"""

from __future__ import annotations

import logging
from pathlib import Path

from cockpit import diagnostics


def _reload_diagnostics(monkeypatch, tmp_path: Path) -> None:
    """Force ``cockpit.diagnostics`` to re-resolve its log path.

    The module caches its handler installation in ``_INITIALIZED`` /
    handlers attached to the ``cockpit`` logger namespace. We can't
    re-import without breaking the singletons other modules already
    hold a reference to, so we reset state by hand.
    """
    monkeypatch.setenv(
        "RESEARCH_AGENT_COCKPIT_CONFIG", str(tmp_path / "cockpit.toml")
    )
    diagnostics._INITIALIZED = False  # noqa: SLF001 - test reset
    cockpit_logger = logging.getLogger("cockpit")
    for handler in list(cockpit_logger.handlers):
        cockpit_logger.removeHandler(handler)
    diagnostics.reset_health()


def test_default_log_path_follows_config_env(monkeypatch, tmp_path: Path):
    target = tmp_path / "custom" / "cockpit.toml"
    monkeypatch.setenv("RESEARCH_AGENT_COCKPIT_CONFIG", str(target))
    monkeypatch.delenv("RESEARCH_AGENT_COCKPIT_LOG", raising=False)
    log_path = diagnostics.default_log_path()
    # The log file sits next to the config file under a logs/ subdir.
    assert log_path == target.parent / "logs" / "cockpit.log"


def test_default_log_path_explicit_override_wins(monkeypatch, tmp_path: Path):
    config_target = tmp_path / "cfg" / "cockpit.toml"
    log_target = tmp_path / "elsewhere" / "audit.log"
    monkeypatch.setenv("RESEARCH_AGENT_COCKPIT_CONFIG", str(config_target))
    monkeypatch.setenv("RESEARCH_AGENT_COCKPIT_LOG", str(log_target))
    # The explicit override beats the config-relative inference.
    assert diagnostics.default_log_path() == log_target


def test_logger_writes_to_file_and_bumps_health(monkeypatch, tmp_path: Path):
    _reload_diagnostics(monkeypatch, tmp_path)
    log = diagnostics.get_logger("test_writes")
    log.warning("first warning")
    log.error("first error")
    # Health state should reflect both records — and only those records
    # since reset_health() ran in _reload_diagnostics.
    state = diagnostics.health_state()
    assert state["warnings"] == 1
    assert state["errors"] == 1
    assert "first error" in state["last_message"]
    assert state["last_level"] == "ERROR"
    # And they should be persisted to disk.
    log_file = diagnostics.default_log_path()
    assert log_file.exists()
    contents = log_file.read_text(encoding="utf-8")
    assert "first warning" in contents
    assert "first error" in contents


def test_info_logs_do_not_light_health_chip(monkeypatch, tmp_path: Path):
    _reload_diagnostics(monkeypatch, tmp_path)
    log = diagnostics.get_logger("test_info_quiet")
    log.info("just an info trace")
    log.debug("nothing visible here")
    state = diagnostics.health_state()
    assert state["warnings"] == 0
    assert state["errors"] == 0
    assert state["last_message"] == ""


def test_reset_health_zeros_counters(monkeypatch, tmp_path: Path):
    _reload_diagnostics(monkeypatch, tmp_path)
    log = diagnostics.get_logger("test_reset")
    log.warning("pretend this happened")
    assert diagnostics.health_state()["warnings"] == 1
    diagnostics.reset_health()
    cleared = diagnostics.health_state()
    assert cleared["warnings"] == 0
    assert cleared["errors"] == 0
    assert cleared["last_message"] == ""
    assert cleared["last_level"] == ""


def test_logger_tolerates_unwritable_log_dir(monkeypatch, tmp_path: Path):
    """Read-only filesystem shouldn't crash the cockpit at import time."""
    # Point the log at a path whose parent we'll make refuse mkdir.
    # On Windows we can't easily chmod a directory to read-only and
    # still get a reliable failure, so we use a path under a regular
    # *file* — mkdir on it raises OSError, which the diagnostics
    # module is supposed to swallow.
    file_blocking_path = tmp_path / "blocker"
    file_blocking_path.write_text("not a directory", encoding="utf-8")
    target = file_blocking_path / "logs" / "cockpit.log"
    monkeypatch.setenv("RESEARCH_AGENT_COCKPIT_LOG", str(target))
    _reload_diagnostics(monkeypatch, tmp_path)
    log = diagnostics.get_logger("test_unwritable")
    # Must not raise even though the file handler couldn't be created.
    log.warning("logged in memory only")
    # The health-state handler is independent of the file handler, so
    # the chip still lights up — a hostile filesystem still surfaces
    # to the user even when the audit trail is unavailable.
    assert diagnostics.health_state()["warnings"] == 1


def test_get_logger_has_no_filesystem_side_effects(monkeypatch, tmp_path: Path):
    """Phase A2 contract: calling ``get_logger`` must not create the log
    directory or open the log file.

    Modules like ``cockpit.app`` bind ``_log = get_logger("app")`` at
    module load. The v0.2 reviewer flagged the pre-A2 implementation for
    eagerly running ``mkdir`` + ``RotatingFileHandler()`` at that point —
    so a plain ``import cockpit.app`` would touch the user's
    ``~/.config/claudescientist/`` even for read-only operations like
    static analysis or test discovery. The lazy file-handler wrapper
    defers all that to first emit.
    """
    _reload_diagnostics(monkeypatch, tmp_path)
    log_dir = diagnostics.default_log_path().parent
    assert not log_dir.exists(), (
        f"log dir {log_dir} pre-exists; cannot meaningfully test laziness"
    )
    diagnostics.get_logger("smoke")
    # Just calling get_logger must NOT create the directory.
    assert not log_dir.exists(), (
        f"get_logger created {log_dir} as a side effect — violates the "
        "Phase A2 lazy-import contract"
    )
    # First actual emission materializes the file (and the parent dir).
    diagnostics.get_logger("smoke").warning("first record")
    assert log_dir.exists()
    assert diagnostics.default_log_path().exists()


def test_importing_cockpit_app_does_not_touch_filesystem(
    monkeypatch, tmp_path: Path
):
    """Even with the App's module-level ``_log = get_logger("app")``,
    importing the module must not create the log directory.

    This is the integration counterpart to
    ``test_get_logger_has_no_filesystem_side_effects``: that one tests
    the diagnostics module in isolation; this one walks the actual
    import path the reviewer was worried about.
    """
    import importlib

    _reload_diagnostics(monkeypatch, tmp_path)
    log_dir = diagnostics.default_log_path().parent
    assert not log_dir.exists()
    # Force a fresh import of cockpit.app. The conftest workspace fixture
    # already reloads it, but here we test the diagnostics-isolated path
    # explicitly.
    importlib.reload(importlib.import_module("cockpit.app"))
    assert not log_dir.exists(), (
        f"importing cockpit.app created {log_dir} as a side effect"
    )
