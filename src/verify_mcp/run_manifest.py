"""Automatic, refreshable run manifests for empirical results."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

TRACKED_SUFFIXES = {".py", ".toml", ".json", ".yaml", ".yml", ".ini", ".cfg"}
LOCKFILE_NAMES = (
    "uv.lock",
    "pyproject.toml",
    "poetry.lock",
    "requirements.txt",
    "environment.yml",
    "conda-lock.yml",
)
REPRO_ENV_KEYS = (
    "PYTHONHASHSEED",
    "CUDA_VISIBLE_DEVICES",
    "CUBLAS_WORKSPACE_CONFIG",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "RESEARCH_AGENT_EMBED_BACKEND",
    "RESEARCH_AGENT_EMBED_MODEL",
    "RESEARCH_AGENT_EMBED_BASE_URL",
)
SECRET_FRAGMENTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")


def hash_file(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _run_git(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def git_snapshot(root: Path) -> dict[str, Any]:
    top = _run_git(root, "rev-parse", "--show-toplevel")
    if top is None:
        return {"available": False}
    git_root = Path(top.strip()).resolve()
    commit = (_run_git(git_root, "rev-parse", "HEAD") or "").strip()
    status = _run_git(git_root, "status", "--porcelain=v1", "--untracked-files=all") or ""
    diff = _run_git(git_root, "diff", "--binary", "HEAD") or ""
    return {
        "available": True,
        "root": str(git_root),
        "commit": commit,
        "dirty": bool(status.strip()),
        "dirty_files": [line[3:] for line in status.splitlines() if len(line) >= 4],
        "working_tree_sha256": _sha256_text(status + "\n" + diff),
    }


def _safe_environment(overrides: dict[str, str] | None = None) -> dict[str, str]:
    values = {key: os.environ[key] for key in REPRO_ENV_KEYS if key in os.environ}
    for key, value in (overrides or {}).items():
        upper = str(key).upper()
        values[str(key)] = (
            "<redacted>"
            if any(fragment in upper for fragment in SECRET_FRAGMENTS)
            else str(value)
        )
    return dict(sorted(values.items()))


def _resolve_file(raw: str | Path, root: Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _command_files(command: str, root: Path) -> list[Path]:
    if not command.strip():
        return []
    try:
        tokens = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        tokens = command.split()
    found: list[Path] = []
    for token in tokens:
        cleaned = token.strip("\"'")
        if Path(cleaned).suffix.lower() not in TRACKED_SUFFIXES:
            continue
        candidate = _resolve_file(cleaned, root)
        if candidate.exists():
            found.append(candidate)
    return found


def _file_entries(
    root: Path,
    *,
    command: str,
    script_path: str | None,
    input_files: list[str] | None,
    config_files: list[str] | None,
) -> list[dict[str, str | None]]:
    paths: dict[str, tuple[Path, set[str]]] = {}

    def add(raw: str | Path, role: str) -> None:
        path = _resolve_file(raw, root)
        key = str(path)
        if key not in paths:
            paths[key] = (path, set())
        paths[key][1].add(role)

    if script_path:
        add(script_path, "script")
    for raw in input_files or []:
        add(raw, "input")
    for raw in config_files or []:
        add(raw, "config")
    for path in _command_files(command, root):
        add(path, "command_file")
    for name in LOCKFILE_NAMES:
        candidate = root / name
        if candidate.is_file():
            add(candidate, "environment_lock")

    return [
        {
            "path": key,
            "roles": ",".join(sorted(roles)),
            "sha256": hash_file(path),
        }
        for key, (path, roles) in sorted(paths.items())
    ]


def capture_run_manifest(
    *,
    command: str = "",
    workspace_root: str | Path | None = None,
    script_path: str | None = None,
    input_files: list[str] | None = None,
    config_files: list[str] | None = None,
    seeds: list[int] | None = None,
    env_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    root = Path(workspace_root or Path.cwd()).expanduser().resolve()
    return {
        "schema_version": 1,
        "workspace_root": str(root),
        "command": command,
        "script_path": str(_resolve_file(script_path, root)) if script_path else None,
        "seeds": list(seeds or []),
        "files": _file_entries(
            root,
            command=command,
            script_path=script_path,
            input_files=input_files,
            config_files=config_files,
        ),
        "git": git_snapshot(root),
        "runtime": {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "python_executable": sys.executable,
            "platform": platform.platform(),
        },
        "environment": _safe_environment(),
        "environment_overrides": _safe_environment(env_overrides),
    }


def manifest_sha256(manifest: dict[str, Any]) -> str:
    encoded = json.dumps(manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return _sha256_text(encoded)


def store_run_manifest(
    con,
    manifest: dict[str, Any],
    *,
    provenance_id: int | None = None,
    seed_run_id: int | None = None,
) -> dict[str, Any]:
    encoded = json.dumps(manifest, ensure_ascii=True, sort_keys=True)
    digest = manifest_sha256(manifest)
    cursor = con.execute(
        """
        INSERT INTO ver_run_manifests(
          provenance_id, seed_run_id, manifest_json, manifest_sha256
        ) VALUES(?,?,?,?)
        """,
        (provenance_id, seed_run_id, encoded, digest),
    )
    return {"manifest_id": int(cursor.lastrowid), "manifest_sha256": digest}


def refresh_run_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    mismatched: list[dict[str, Any]] = []
    for entry in manifest.get("files", []):
        path = Path(str(entry.get("path", "")))
        expected = entry.get("sha256")
        actual = hash_file(path)
        if actual != expected:
            mismatched.append(
                {"field": "file", "path": str(path), "expected": expected, "actual": actual}
            )

    root = Path(str(manifest.get("workspace_root") or Path.cwd()))
    expected_git = manifest.get("git") or {"available": False}
    actual_git = git_snapshot(root)
    for field in ("available", "commit", "dirty", "working_tree_sha256"):
        if expected_git.get(field) != actual_git.get(field):
            mismatched.append(
                {
                    "field": f"git.{field}",
                    "expected": expected_git.get(field),
                    "actual": actual_git.get(field),
                }
            )

    expected_runtime = manifest.get("runtime") or {}
    current_runtime = {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
    }
    for field, expected in expected_runtime.items():
        if current_runtime.get(field) != expected:
            mismatched.append(
                {
                    "field": f"runtime.{field}",
                    "expected": expected,
                    "actual": current_runtime.get(field),
                }
            )

    expected_environment = manifest.get("environment") or {}
    current_environment = _safe_environment()
    if expected_environment != current_environment:
        mismatched.append(
            {
                "field": "environment",
                "expected": expected_environment,
                "actual": current_environment,
            }
        )
    return mismatched
