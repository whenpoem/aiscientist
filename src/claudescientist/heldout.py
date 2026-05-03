"""Pure file operations for sequestered datasets.

This module owns only file-level utilities (path resolution, manifest hashing,
manifest read/write). All SQL-touching logic and the CLI live in
:mod:`verify_mcp.heldout` and :mod:`verify_mcp.heldout_cli` because the
``ver_heldout_budgets`` table is a verify-business state and shares an FK with
``ver_heldout_queries``.

The ``python -m claudescientist.heldout`` invocation continues to work because
the CLI ``main`` is re-imported below; it dispatches into the verify-side
implementation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from claudescientist.runtime import heldout_root, now_utc_iso


def dataset_root(dataset: str) -> Path:
    return heldout_root() / dataset


def manifest_path(dataset: str | Path) -> Path:
    root = Path(dataset)
    if root.name == "manifest.json":
        return root
    return root / "manifest.json"


def _iter_dataset_files(root: Path) -> Iterable[Path]:
    pointer_suffix = "." + "heldout" + "-" + "pointer"
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*")):
        if (
            path.is_file()
            and path.name != "manifest.json"
            and not path.name.endswith(pointer_suffix)
        ):
            yield path


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def compute_manifest(root: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    if root.is_file():
        files = [root]
    else:
        files = list(_iter_dataset_files(root))
    for file_path in files:
        if root.is_file():
            relative = file_path.name
        else:
            relative = str(file_path.relative_to(root)).replace("\\", "/")
        data = file_path.read_bytes()
        file_hash = _sha256_bytes(data)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
        entries.append(
            {
                "path": relative,
                "size": file_path.stat().st_size,
                "sha256": file_hash,
            }
        )
    manifest_sha256 = digest.hexdigest()
    return {
        "dataset": root.name,
        "root": str(root),
        "manifest_sha256": manifest_sha256,
        "generated_at": now_utc_iso(),
        "files": entries,
    }


def load_manifest(root: Path) -> dict[str, Any] | None:
    manifest_file = manifest_path(root)
    if not manifest_file.exists():
        return None
    try:
        return json.loads(manifest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def write_manifest(root: Path, manifest: dict[str, Any]) -> Path:
    manifest_file = manifest_path(root)
    manifest_file.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest_file


# ---------------------------------------------------------------------------
# CLI entry point preserved for `python -m claudescientist.heldout`.
#
# The actual command implementations live in verify_mcp.heldout_cli. We
# expose ``main`` as a thin wrapper that performs the import lazily; this
# both forwards the call and avoids a top-level circular import (since
# verify_mcp.heldout itself imports from this module).
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Forward to :func:`verify_mcp.heldout_cli.main` (lazy import)."""
    from verify_mcp.heldout_cli import main as _verify_main

    return _verify_main(argv)


__all__ = [
    "dataset_root",
    "manifest_path",
    "compute_manifest",
    "load_manifest",
    "write_manifest",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
