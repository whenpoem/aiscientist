"""Shared runtime helpers for paths, timestamps, and lightweight schema tracking."""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import sqlite3
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_STATE_DIR = Path(".research-agent")
DEFAULT_DB_NAME = "state.db"
HELDOUT_DIR_ENV = "RESEARCH_AGENT_HELDOUT_DIR"
CLAUDE_PROJECT_DIR_ENV = "CLAUDE_PROJECT_DIR"
# ``RESEARCH_AGENT_WORKSPACE_ROOT`` is the documented v5.1 name. Keep the
# shorter spelling as a compatibility alias for v5.1.0/5.1.1 callers.
RESEARCH_AGENT_WORKSPACE_ROOT_ENV = "RESEARCH_AGENT_WORKSPACE_ROOT"
RESEARCH_AGENT_WORKSPACE_ENV = "RESEARCH_AGENT_WORKSPACE"
MIGRATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS ra_migrations (
  component TEXT PRIMARY KEY,
  schema_sha256 TEXT NOT NULL,
  schema_version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'applied',
  error TEXT NOT NULL DEFAULT '',
  applied_at TEXT NOT NULL
);
"""
COCKPIT_EVENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS cockpit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  payload TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  source TEXT
);
"""
COCKPIT_EVENT_INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_cockpit_events_created_at
  ON cockpit_events(created_at);
"""


def _looks_like_repo_root(path: Path) -> bool:
    return (path / "pyproject.toml").exists() and (path / ".claude").is_dir()


def project_root(start: Path | None = None) -> Path | None:
    """Resolve a ClaudeScientist source checkout for development assets.

    Claude Code normally exports ``CLAUDE_PROJECT_DIR``. Prefer that when it
    points at a checkout; otherwise walk upward from ``start`` (or cwd). This
    keeps hooks, MCP servers, and the cockpit on the same runtime files even
    when a session is launched from a subdirectory.
    """
    project_dir = os.environ.get(CLAUDE_PROJECT_DIR_ENV)
    if project_dir:
        candidate = Path(project_dir).expanduser().resolve()
        if _looks_like_repo_root(candidate):
            return candidate

    cur = (start or Path.cwd()).expanduser().resolve()
    for candidate in (cur, *cur.parents):
        if _looks_like_repo_root(candidate):
            return candidate
    return None


def installation_root() -> Path:
    """Return the installed package root or the editable source checkout.

    This location owns bundled hooks and static assets. It must never decide
    where a user's research state is written.
    """
    checkout = project_root(Path(__file__).resolve())
    if checkout is not None:
        return checkout
    return Path(__file__).resolve().parent


def _looks_like_workspace_root(path: Path) -> bool:
    return any(
        (
            (path / ".research-agent").exists(),
            (path / ".git").exists(),
            (path / "pyproject.toml").exists(),
            (path / "AGENTS.md").exists(),
        )
    )


def workspace_root(start: Path | None = None) -> Path:
    """Resolve the active research workspace independently of installation.

    Explicit ``RESEARCH_AGENT_WORKSPACE_ROOT`` wins, followed by the legacy
    ``RESEARCH_AGENT_WORKSPACE`` alias. Agent hosts commonly provide
    ``CLAUDE_PROJECT_DIR`` and that directory is accepted even when it is an
    ordinary research repository with no ClaudeScientist source files.
    Otherwise the nearest recognizable project ancestor is used, falling back
    to the supplied start directory (or current working directory).
    """
    explicit = os.environ.get(RESEARCH_AGENT_WORKSPACE_ROOT_ENV) or os.environ.get(
        RESEARCH_AGENT_WORKSPACE_ENV
    )
    if explicit:
        return Path(explicit).expanduser().resolve()
    host_workspace = os.environ.get(CLAUDE_PROJECT_DIR_ENV)
    if host_workspace:
        return Path(host_workspace).expanduser().resolve()

    current = (start or Path.cwd()).expanduser().resolve()
    for candidate in (current, *current.parents):
        if _looks_like_workspace_root(candidate):
            return candidate
    return current


def state_db_path() -> Path:
    override = os.environ.get("RESEARCH_AGENT_DB_PATH")
    if override:
        return Path(override).expanduser()
    state_dir = os.environ.get("RESEARCH_AGENT_STATE_DIR")
    if state_dir:
        return Path(state_dir).expanduser() / DEFAULT_DB_NAME
    return workspace_root() / DEFAULT_STATE_DIR / DEFAULT_DB_NAME


def runtime_path(*parts: str) -> Path:
    return state_db_path().parent.joinpath(*parts)


def heldout_root() -> Path:
    override = os.environ.get(HELDOUT_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".research-agent" / "heldout"


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def cache_key(path: Path | None = None) -> str:
    return str((path or state_db_path()).resolve())


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_sqlite(path: Path | None = None, *, timeout: float = 5.0) -> sqlite3.Connection:
    target = ensure_parent(path or state_db_path())
    con = sqlite3.connect(str(target), timeout=timeout, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con


def begin_immediate_with_retry(
    con: sqlite3.Connection,
    *,
    attempts: int = 3,
    base_delay: float = 0.02,
) -> None:
    """Acquire SQLite's write lock with a short bounded jittered retry.

    The project remains a single-user local SQLite system, but Codex hooks and
    MCP processes can briefly overlap. Retrying only ``locked``/``busy``
    errors avoids losing otherwise valid writes without masking other database
    failures or turning contention into an unbounded hang.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    for attempt in range(attempts):
        try:
            con.execute("BEGIN IMMEDIATE")
            return
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if not any(marker in message for marker in ("locked", "busy")):
                raise
            if attempt == attempts - 1:
                raise
            delay = base_delay * (2**attempt) + random.uniform(0.0, base_delay)
            time.sleep(delay)


def connect_existing_sqlite(
    path: Path | None = None,
    *,
    timeout: float = 2.0,
) -> sqlite3.Connection | None:
    """Open an existing state DB without creating it.

    Short-lived hooks use this helper so first-run or malformed workspaces
    still fail open: a missing DB means "nothing to read", not "create an
    empty runtime DB during a lifecycle hook".
    """
    target = path or state_db_path()
    if not target.exists():
        return None
    try:
        con = sqlite3.connect(str(target), timeout=timeout, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA foreign_keys=ON;")
    except sqlite3.DatabaseError:
        try:
            con.close()
        except UnboundLocalError:
            pass
        return None
    return con


def ensure_columns(
    con: sqlite3.Connection,
    table_name: str,
    column_defs: dict[str, str],
) -> None:
    existing = {row["name"] for row in con.execute(f"PRAGMA table_info({table_name})").fetchall()}
    for column_name, column_def in column_defs.items():
        if column_name not in existing:
            con.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")


def _ensure_migration_columns(con: sqlite3.Connection) -> None:
    ensure_columns(
        con,
        "ra_migrations",
        {
            "schema_version": "INTEGER NOT NULL DEFAULT 1",
            "status": "TEXT NOT NULL DEFAULT 'applied'",
            "error": "TEXT NOT NULL DEFAULT ''",
        },
    )


def apply_schema_migration(
    con: sqlite3.Connection,
    component: str,
    schema_text: str,
    *,
    schema_version: int = 1,
) -> None:
    con.executescript(MIGRATION_SCHEMA)
    _ensure_migration_columns(con)
    schema_hash = hashlib.sha256(schema_text.encode("utf-8")).hexdigest()
    row = con.execute(
        "SELECT schema_sha256, schema_version FROM ra_migrations WHERE component = ?",
        (component,),
    ).fetchone()
    if row is not None and row["schema_sha256"] != schema_hash:
        warnings.warn(
            (
                f"Schema hash changed for {component}; applying updated schema and "
                "refreshing the recorded hash."
            ),
            stacklevel=2,
        )
    con.execute(
        """
        INSERT INTO ra_migrations(
          component, schema_sha256, schema_version, status, error, applied_at
        )
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(component) DO UPDATE SET
          schema_sha256 = excluded.schema_sha256,
          schema_version = excluded.schema_version,
          status = excluded.status,
          error = excluded.error,
          applied_at = excluded.applied_at
        """,
        (component, schema_hash, schema_version, "applying", "", now_utc_iso()),
    )
    try:
        con.executescript(schema_text)
    except Exception as exc:
        con.execute(
            """
            UPDATE ra_migrations
            SET status = ?, error = ?, applied_at = ?
            WHERE component = ?
            """,
            ("failed", str(exc)[:500], now_utc_iso(), component),
        )
        raise
    con.execute(
        """
        INSERT INTO ra_migrations(
          component, schema_sha256, schema_version, status, error, applied_at
        )
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(component) DO UPDATE SET
          schema_sha256 = excluded.schema_sha256,
          schema_version = excluded.schema_version,
          status = excluded.status,
          error = excluded.error,
          applied_at = excluded.applied_at
        """,
        (component, schema_hash, schema_version, "applied", "", now_utc_iso()),
    )


def emit_cockpit_event(
    con: sqlite3.Connection,
    kind: str,
    payload: dict[str, Any],
    *,
    source: str | None = None,
) -> int:
    """Append a row to ``cockpit_events``.

    ``source`` is an optional provenance tag (e.g. ``"memory_mcp"``,
    ``"verify_mcp"``, ``"cockpit_mcp"``, ``"cockpit_user"``) so the TUI
    can answer the "who emitted this event" question in the Detail
    pane. Older callers that don't pass ``source`` get ``NULL`` and
    the UI renders them as ``unknown`` — the data path stays
    backwards-compatible.
    """
    con.execute(COCKPIT_EVENT_SCHEMA)
    con.execute(COCKPIT_EVENT_INDEX_SCHEMA)
    ensure_columns(con, "cockpit_events", {"source": "TEXT"})
    cursor = con.execute(
        "INSERT INTO cockpit_events(kind, payload, created_at, source) VALUES(?,?,?,?)",
        (kind, json.dumps(payload, ensure_ascii=True), now_utc_iso(), source),
    )
    return int(cursor.lastrowid or 0)


def read_json_file(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return data


def write_json_file(path: Path, payload: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Numeric-claim recognition (project-wide).
#
# These constants describe how the project recognises a numeric claim in any
# textual stream (script stdout, commit message, manuscript paragraph). They
# live in runtime because both verify_mcp.provenance and the leakage /
# provenance hooks need them; keeping them in any single business module would
# force the others to reach across layers.
# ---------------------------------------------------------------------------

METRIC_WORDS = (
    "acc",
    "accuracy",
    "f1",
    "auc",
    "auroc",
    "auprc",
    "loss",
    "precision",
    "recall",
    "mse",
    "rmse",
    "mae",
    "bleu",
    "rouge",
    "score",
    "metric",
    "error",
)
NOISE_METRIC_WORDS = (
    "epoch",
    "step",
    "seed",
    "batch",
    "sample",
    "param",
    "second",
    "minute",
    "hour",
    "iteration",
    "iter",
    "token",
    "ms",
    "sec",
    "time",
    "throughput",
    "speed",
    "wall",
)
METRIC_LABEL_FRAGMENT = (
    r"(?:best|train|val|valid|validation|dev|test|holdout|oof|cv|cross[ -]?val)?"
    r"[ _-]*"
    r"(?:top[ -]?\d+[ _-]*)?"
    r"(?:acc(?:uracy)?|f1(?:[ _-]?score)?|auc|auroc|auprc|loss|precision|recall|"
    r"mse|rmse|mae|bleu|rouge(?:[- ]?[a-z0-9]+)?|score|metric|error)"
)
METRIC_RE = re.compile(
    rf"(?P<label>{METRIC_LABEL_FRAGMENT})\s*(?:[:=]|is|\s)\s*"
    r"(?P<value>[-+]?\d+(?:\.\d+)?%?)",
    re.IGNORECASE,
)
_LABEL_BEFORE_VALUE_RE = re.compile(
    rf"(?P<label>{METRIC_LABEL_FRAGMENT})\s*(?:[:=]|is)\s*"
    r"(?P<value>[-+]?\d+(?:\.\d+)?%?)",
    re.IGNORECASE,
)
_LABEL_AND_VALUE_RE = re.compile(
    rf"(?P<label>{METRIC_LABEL_FRAGMENT})\s+"
    r"(?P<value>[-+]?\d+(?:\.\d+)?%?)",
    re.IGNORECASE,
)
_VALUE_BEFORE_LABEL_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<value>[-+]?\d+(?:\.\d+)?%?)\s+"
    rf"(?P<label>{METRIC_LABEL_FRAGMENT})\b",
    re.IGNORECASE,
)

NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?%?")


def extract_metric_tokens(text: str) -> list[str]:
    """Return labelled numeric values found in ``text``; fall back to bare numbers."""
    values = [match.group("value") for match in METRIC_RE.finditer(text)]
    if values:
        return values
    return NUMBER_RE.findall(text)


def normalize_metric_label(label: str) -> str:
    """Normalize a metric label to a stable snake-ish claim key."""
    label = label.strip().lower()
    label = label.replace("%", "pct")
    label = label.replace("/", "_")
    label = re.sub(r"[^a-z0-9]+", "_", label)
    label = re.sub(r"_+", "_", label).strip("_")
    return label[:64]


def looks_like_metric_label(label: str) -> bool:
    lowered = label.lower()
    has_metric_word = any(word in lowered for word in METRIC_WORDS)
    has_noise_word = any(word in lowered for word in NOISE_METRIC_WORDS)
    return has_metric_word and not has_noise_word


def extract_labeled_metric_records(text: str) -> list[tuple[str, str]]:
    """Return ``(normalized_label, value)`` pairs for labelled metric output.

    This deliberately ignores bare numbers. Hooks use it to avoid treating
    years, seed counts, version numbers, and narrative quantities as result
    claims.
    """
    records: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        found_on_line = False
        for pattern in (
            _LABEL_BEFORE_VALUE_RE,
            _LABEL_AND_VALUE_RE,
            _VALUE_BEFORE_LABEL_RE,
        ):
            for match in pattern.finditer(line):
                label = normalize_metric_label(match.group("label"))
                value = match.group("value")
                if not label or not looks_like_metric_label(label):
                    continue
                record = (label, value)
                if record in seen:
                    continue
                seen.add(record)
                records.append(record)
                found_on_line = True
        if found_on_line:
            continue
        lowered = line.lower()
        if not any(word in lowered for word in METRIC_WORDS):
            continue
        values = extract_metric_tokens(line)
        if not values:
            continue
        fallback_label = normalize_metric_label(line.split(":")[0].split("=")[0])
        if not looks_like_metric_label(fallback_label):
            fallback_label = "bash_metric"
        record = (fallback_label, values[0])
        if record not in seen:
            seen.add(record)
            records.append(record)
    return records


# ---------------------------------------------------------------------------
# Component bootstrap registry.
#
# Modules that own SQLite schemas register themselves implicitly through the
# ``KNOWN_BOOTSTRAP_COMPONENTS`` tuple. Cockpit and other entry points call
# ``bootstrap_all()`` to ensure every known schema is ready before reading.
# Adding a new MCP server in the future means appending its bootstrap module
# here — and only here.
# ---------------------------------------------------------------------------

KNOWN_BOOTSTRAP_COMPONENTS: tuple[str, ...] = (
    "memory_mcp.db",
    "verify_mcp.db",
    "prove_mcp.db",
)


def bootstrap_all() -> None:
    """Trigger bootstrap on every component registered in ``KNOWN_BOOTSTRAP_COMPONENTS``.

    Each named module must expose a module-level ``bootstrap()`` function that
    is idempotent. Called by the cockpit before it reads cross-component
    tables; safe to invoke multiple times per process.
    """
    from importlib import import_module

    for module_name in KNOWN_BOOTSTRAP_COMPONENTS:
        module = import_module(module_name)
        module.bootstrap()
