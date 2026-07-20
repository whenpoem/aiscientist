"""Workspace-local configuration for installed ClaudeScientist commands.

The public Codex plugin starts ClaudeScientist from an installed Python package,
so a source-checkout ``.env`` file is not a reliable configuration channel.
This module owns the small, non-secret TOML file used by ordinary research
workspaces and maps its values to the existing runtime environment contract.
"""

from __future__ import annotations

import json
import os
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .runtime import workspace_root

CONFIG_VERSION = 1
CONFIG_RELATIVE_PATH = Path(".research-agent") / "config.toml"
EMBED_BACKENDS = ("local", "openai", "mock")

_ENVIRONMENT_KEYS = {
    "RESEARCH_AGENT_EMBED_BACKEND",
    "RESEARCH_AGENT_EMBED_MODEL",
    "RESEARCH_AGENT_EMBED_BASE_URL",
    "RESEARCH_AGENT_HELDOUT_DIR",
    "RESEARCH_AGENT_AUTO_PRUNE",
    "RESEARCH_AGENT_LEAN_ENABLED",
    "LEAN_PROJECT_PATH",
}


@dataclass(frozen=True)
class WorkspaceConfig:
    """Parsed workspace configuration and any validation errors."""

    path: Path
    values: dict[str, str]
    errors: tuple[str, ...] = ()
    exists: bool = False


def config_path(root: str | Path | None = None) -> Path:
    base = (
        Path(root).expanduser().resolve()
        if root is not None
        else workspace_root()
    )
    return base / CONFIG_RELATIVE_PATH


def _string(section: dict[str, Any], key: str, errors: list[str]) -> str | None:
    value = section.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        errors.append(f"{key} must be a string")
        return None
    return value.strip()


def _boolean(section: dict[str, Any], key: str, errors: list[str]) -> bool | None:
    value = section.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        errors.append(f"{key} must be true or false")
        return None
    return value


def _section(payload: dict[str, Any], name: str, errors: list[str]) -> dict[str, Any]:
    value = payload.get(name, {})
    if not isinstance(value, dict):
        errors.append(f"[{name}] must be a TOML table")
        return {}
    return value


def _resolve_path(value: str, root: Path) -> str:
    expanded = Path(os.path.expandvars(os.path.expanduser(value)))
    if not expanded.is_absolute():
        expanded = root / expanded
    return str(expanded.resolve())


def read_workspace_config(root: str | Path | None = None) -> WorkspaceConfig:
    path = config_path(root)
    if not path.is_file():
        return WorkspaceConfig(path=path, values={}, exists=False)

    errors: list[str] = []
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        return WorkspaceConfig(
            path=path,
            values={},
            errors=(f"could not read TOML: {exc}",),
            exists=True,
        )

    version = payload.get("version", CONFIG_VERSION)
    if version != CONFIG_VERSION:
        errors.append(f"unsupported config version {version!r}; expected {CONFIG_VERSION}")

    root_path = path.parents[1]
    values: dict[str, str] = {}

    embedding = _section(payload, "embedding", errors)
    backend = _string(embedding, "backend", errors)
    if backend:
        backend = backend.lower()
        if backend not in EMBED_BACKENDS:
            errors.append(
                "embedding.backend must be one of " + ", ".join(EMBED_BACKENDS)
            )
        else:
            values["RESEARCH_AGENT_EMBED_BACKEND"] = backend
    model = _string(embedding, "model", errors)
    if model:
        values["RESEARCH_AGENT_EMBED_MODEL"] = model
    base_url = _string(embedding, "base_url", errors)
    if base_url is not None:
        values["RESEARCH_AGENT_EMBED_BASE_URL"] = base_url

    heldout = _section(payload, "heldout", errors)
    heldout_dir = _string(heldout, "directory", errors)
    if heldout_dir:
        values["RESEARCH_AGENT_HELDOUT_DIR"] = _resolve_path(heldout_dir, root_path)

    research = _section(payload, "research", errors)
    auto_prune = _boolean(research, "auto_prune", errors)
    if auto_prune is not None:
        values["RESEARCH_AGENT_AUTO_PRUNE"] = "1" if auto_prune else "0"

    lean = _section(payload, "lean", errors)
    lean_enabled = _boolean(lean, "enabled", errors)
    if lean_enabled is not None:
        values["RESEARCH_AGENT_LEAN_ENABLED"] = "1" if lean_enabled else "0"
    lean_project = _string(lean, "project_path", errors)
    if lean_project:
        values["LEAN_PROJECT_PATH"] = _resolve_path(lean_project, root_path)

    return WorkspaceConfig(
        path=path,
        values=values,
        errors=tuple(errors),
        exists=True,
    )


def apply_workspace_config(config: WorkspaceConfig) -> dict[str, str]:
    """Apply valid values without overriding an explicit process environment."""

    applied: dict[str, str] = {}
    for key, value in config.values.items():
        if key not in os.environ:
            os.environ[key] = value
            applied[key] = value
    return applied


@contextmanager
def configured_environment(
    root: str | Path | None = None,
) -> Iterator[WorkspaceConfig]:
    """Temporarily load one workspace config into the current process."""

    before = {key: os.environ.get(key) for key in _ENVIRONMENT_KEYS}
    config = read_workspace_config(root)
    apply_workspace_config(config)
    try:
        yield config
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_workspace_config(settings: dict[str, Any]) -> str:
    embedding = settings.get("embedding", {})
    heldout = settings.get("heldout", {})
    research = settings.get("research", {})
    lean = settings.get("lean", {})
    lines = [
        "# ClaudeScientist workspace configuration.",
        "# Do not store API keys or other secrets in this file.",
        f"version = {CONFIG_VERSION}",
        "",
        "[embedding]",
        f"backend = {_toml_string(str(embedding.get('backend', 'local')))}",
        f"model = {_toml_string(str(embedding.get('model', '')))}",
        f"base_url = {_toml_string(str(embedding.get('base_url', '')))}",
        "",
        "[heldout]",
        f"directory = {_toml_string(str(heldout.get('directory', '')))}",
        "",
        "[research]",
        f"auto_prune = {'true' if bool(research.get('auto_prune', False)) else 'false'}",
        "",
        "[lean]",
        f"enabled = {'true' if bool(lean.get('enabled', False)) else 'false'}",
        f"project_path = {_toml_string(str(lean.get('project_path', '')))}",
        "",
    ]
    return "\n".join(lines)


def write_workspace_config(
    settings: dict[str, Any], root: str | Path | None = None
) -> Path:
    path = config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".toml.tmp")
    temporary.write_text(render_workspace_config(settings), encoding="utf-8")
    temporary.replace(path)
    return path


__all__ = [
    "CONFIG_RELATIVE_PATH",
    "CONFIG_VERSION",
    "EMBED_BACKENDS",
    "WorkspaceConfig",
    "apply_workspace_config",
    "config_path",
    "configured_environment",
    "read_workspace_config",
    "render_workspace_config",
    "write_workspace_config",
]
