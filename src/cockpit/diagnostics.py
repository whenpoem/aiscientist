"""Cockpit-side observability: logging + health-state singleton.

Before Phase A, the cockpit swallowed nearly every ``except`` branch with
``pragma: no cover - defensive`` so a crash in a side-effect wouldn't kill
the UI. The cost was that **the user never saw an error and the developer
had nowhere to look**. Phase A introduces this module so:

1. Defensive ``except`` sites can call :func:`get_logger().exception(...)`
   and have the trace land in ``<config-dir>/logs/cockpit.log``.
2. The HUD reads :func:`health_state` and surfaces a ``⚠`` chip when the
   cockpit has logged warnings or errors during this session. That chip is
   the user-facing tell that "something is up, check the log".

Path resolution mirrors :func:`cockpit.settings.default_config_path` so a
single env var override (``RESEARCH_AGENT_COCKPIT_CONFIG``) relocates both
settings and logs in tandem — important for the test suite, which pins
both into ``tmp_path`` via ``conftest.workspace``.

Behavioral notes:

- :func:`get_logger` is **side-effect free at call time**. It attaches a
  :class:`_LazyFileHandler` plus a :class:`_HealthHandler` to the
  ``cockpit`` logger namespace on first call, but **neither handler
  touches the filesystem until a record is actually emitted**. This is
  important because modules like ``cockpit.app`` do
  ``_log = get_logger("app")`` at module load — without the lazy file
  handler, simply ``import cockpit.app`` would create the
  ``<config-dir>/logs/`` directory and open the rotating file, which
  the v0.2 reviewer flagged as a hidden side effect.
- Failures **to set up the log file itself** are swallowed (we have
  nowhere to log them). The lazy handler records a ``_init_failed``
  flag and stops trying so a misconfigured filesystem doesn't trigger
  per-record retries.
- ``health_state()`` is monotonic within a process: the counts only go up.
  Resetting requires :func:`reset_health` (used by tests + the
  ``:health`` command palette entry).
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Mirror the cockpit's config env-var so logs follow settings into tmp_path
# during tests. The path itself can also be overridden explicitly with
# RESEARCH_AGENT_COCKPIT_LOG, which is what a power user would set to
# pipe logs into journald / their own collector.
_CONFIG_ENV = "RESEARCH_AGENT_COCKPIT_CONFIG"
_LOG_ENV = "RESEARCH_AGENT_COCKPIT_LOG"
_LEVEL_ENV = "RESEARCH_AGENT_COCKPIT_LOG_LEVEL"

# Rotation: 5 files × ~512 KiB ≈ 2.5 MiB on disk worst case. The cockpit
# is a long-running UI process; without rotation a single bad run with a
# tight error loop could grow the log unbounded.
_LOG_MAX_BYTES = 512 * 1024
_LOG_BACKUP_COUNT = 5

_INIT_LOCK = threading.Lock()
_INITIALIZED = False

_HEALTH_LOCK = threading.Lock()
_HEALTH: dict[str, object] = {
    "errors": 0,
    "warnings": 0,
    "last_message": "",
    "last_level": "",
    "last_at": "",
}


def default_log_path() -> Path:
    """Return ``<config-dir>/logs/cockpit.log`` (or the env override).

    Resolution order:
      1. ``RESEARCH_AGENT_COCKPIT_LOG`` (explicit override; absolute path)
      2. Same parent as ``RESEARCH_AGENT_COCKPIT_CONFIG`` if it is set
         (keeps test-isolation honest — conftest pins both).
      3. Platform-default: ``%APPDATA%/claudescientist/logs/cockpit.log``
         on Windows, ``$XDG_CONFIG_HOME/claudescientist/logs/...`` or
         ``~/.config/claudescientist/logs/...`` elsewhere.
    """
    explicit = os.environ.get(_LOG_ENV)
    if explicit:
        return Path(explicit)
    config_override = os.environ.get(_CONFIG_ENV)
    if config_override:
        # The settings env var points at the TOML file; the log sits
        # next to it in a ``logs/`` subdir so tests using tmp_path
        # produce one isolated tree per test.
        return Path(config_override).parent / "logs" / "cockpit.log"
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "claudescientist" / "logs" / "cockpit.log"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "claudescientist" / "logs" / "cockpit.log"


class _LazyFileHandler(logging.Handler):
    """Rotating-file handler wrapper that defers I/O to first ``emit``.

    The cockpit attaches this handler at logger setup time (so the
    handler list is correctly populated), but **the underlying
    :class:`logging.handlers.RotatingFileHandler` — and the ``mkdir``
    call that creates the ``logs/`` directory — only run when a log
    record actually arrives**.

    Why bother? Modules like ``cockpit.app`` call ``get_logger("app")``
    at module load to bind a ``_log`` reference for their ``except``
    sites. The pre-Phase-A2 implementation would create the logs
    directory and open the rotating file on every cockpit module import,
    including tests that never emit anything. The lazy wrapper keeps the
    user-facing behavior identical (records still land in the file) but
    makes plain imports filesystem-clean.

    Initialization failures (read-only FS, missing permissions, path
    too long) are recorded in ``_init_failed`` and no further attempts
    are made — without this guard a hostile filesystem would trigger
    per-record retries and slow the cockpit's tick loop.
    """

    def __init__(self) -> None:
        super().__init__()
        self._delegate: logging.Handler | None = None
        self._init_failed = False

    def _ensure_delegate(self) -> None:
        if self._delegate is not None or self._init_failed:
            return
        try:
            target = default_log_path()
            target.parent.mkdir(parents=True, exist_ok=True)
            handler: logging.Handler = RotatingFileHandler(
                target,
                maxBytes=_LOG_MAX_BYTES,
                backupCount=_LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
        except OSError:
            # Read-only FS, path too long, etc. The health handler still
            # tracks the WARNING/ERROR in memory so the HUD chip still
            # paints — we just lose the persistent audit trail.
            self._init_failed = True
            return
        if self.formatter is not None:
            handler.setFormatter(self.formatter)
        self._delegate = handler

    def emit(self, record: logging.LogRecord) -> None:
        self._ensure_delegate()
        if self._delegate is not None:
            self._delegate.emit(record)

    def setFormatter(self, fmt) -> None:  # noqa: N802 - stdlib signature
        super().setFormatter(fmt)
        if self._delegate is not None:
            self._delegate.setFormatter(fmt)

    def close(self) -> None:
        if self._delegate is not None:
            try:
                self._delegate.close()
            except Exception:  # pragma: no cover - defensive
                pass
        super().close()


class _HealthHandler(logging.Handler):
    """Logging handler that updates the in-memory health state.

    Lives alongside the rotating file handler so every WARNING/ERROR
    that hits the log also bumps the counters the HUD reads. INFO
    and DEBUG records are ignored to keep the chip honest — a chatty
    info log shouldn't paint a warning glyph.
    """

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        if record.levelno < logging.WARNING:
            return
        with _HEALTH_LOCK:
            if record.levelno >= logging.ERROR:
                _HEALTH["errors"] = int(_HEALTH["errors"]) + 1
            else:
                _HEALTH["warnings"] = int(_HEALTH["warnings"]) + 1
            try:
                _HEALTH["last_message"] = record.getMessage()
            except Exception:  # pragma: no cover - record formatting edge
                _HEALTH["last_message"] = "<unformattable log record>"
            _HEALTH["last_level"] = record.levelname
            _HEALTH["last_at"] = datetime.now(timezone.utc).isoformat()


def _resolve_level() -> int:
    raw = os.environ.get(_LEVEL_ENV, "").strip().upper()
    if not raw:
        return logging.INFO
    # Map well-known names; ignore unknown values rather than crashing
    # the cockpit before it even mounts.
    return logging.getLevelName(raw) if raw in logging._nameToLevel else logging.INFO


def _ensure_initialized() -> None:
    """Attach cockpit log handlers to the ``cockpit`` logger namespace.

    Idempotent. **No filesystem operations happen here** — the file
    handler is the lazy :class:`_LazyFileHandler` which only opens the
    log file on first record emission. Calling this from
    :func:`get_logger` keeps the per-call cost at "a few dict/list
    operations" so a module-level ``_log = get_logger("app")`` stays
    cheap.
    """
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _INIT_LOCK:
        if _INITIALIZED:
            return
        logger = logging.getLogger("cockpit")
        # The cockpit owns this logger namespace. Set propagate=False so
        # any root-level configuration the host process installs (pytest's
        # caplog, a research script's basicConfig) does not double-emit
        # cockpit messages.
        logger.propagate = False
        logger.setLevel(_resolve_level())
        # Clear any handlers a hot-reload (conftest.workspace) may have
        # left attached — otherwise each test would add another file
        # handler and exhaust the OS file-handle table.
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
        file_handler = _LazyFileHandler()
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(_HealthHandler())
        _INITIALIZED = True


def get_logger(name: str = "cockpit") -> logging.Logger:
    """Return the cockpit logger (or a child of it).

    Children inherit handlers from the ``cockpit`` namespace, so a call
    like ``get_logger("cockpit.app")`` writes to the same file as
    ``get_logger("cockpit.tui")``. The hierarchical naming makes the log
    grep-friendly — `grep "cockpit.app " cockpit.log` shows only what
    the App emitted.
    """
    _ensure_initialized()
    if name == "cockpit":
        return logging.getLogger("cockpit")
    if not name.startswith("cockpit."):
        name = f"cockpit.{name}"
    return logging.getLogger(name)


def health_state() -> dict:
    """Return a snapshot of warnings/errors logged this session.

    Snapshot keys: ``errors`` (int), ``warnings`` (int),
    ``last_message`` (str), ``last_level`` (``"WARNING"``/``"ERROR"``),
    ``last_at`` (ISO timestamp, UTC). The HUD reads this each refresh
    tick; the dict is returned as a copy so the caller can't mutate the
    shared state by accident.
    """
    _ensure_initialized()
    with _HEALTH_LOCK:
        return dict(_HEALTH)


def reset_health() -> None:
    """Clear the in-memory health counters.

    Used by the test suite (conftest does not — yet — call this, but the
    workspace fixture's module reload effectively resets state by hot-
    reloading the diagnostics module). Also reserved for a future
    ``:health clear`` command palette entry once the user has acknowledged
    the surfaced warnings.
    """
    with _HEALTH_LOCK:
        _HEALTH["errors"] = 0
        _HEALTH["warnings"] = 0
        _HEALTH["last_message"] = ""
        _HEALTH["last_level"] = ""
        _HEALTH["last_at"] = ""


__all__ = [
    "default_log_path",
    "get_logger",
    "health_state",
    "reset_health",
]
