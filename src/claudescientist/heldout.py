"""Held-out dataset registration and inspection helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Iterable

from claudescientist.runtime import now_utc_iso
from verify_mcp.db import bootstrap as verify_bootstrap
from verify_mcp.db import tx

DEFAULT_HELDOUT_BUDGET = 5
HELDOUT_DIR_ENV = "RESEARCH_AGENT_HELDOUT_DIR"


def heldout_root() -> Path:
    override = os.environ.get(HELDOUT_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".research-agent" / "heldout"


def dataset_root(dataset: str) -> Path:
    return heldout_root() / dataset


def manifest_path(dataset: str | Path) -> Path:
    root = Path(dataset)
    if root.name == "manifest.json":
        return root
    return root / "manifest.json"


def _iter_dataset_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*")):
        if (
            path.is_file()
            and path.name != "manifest.json"
            and not path.name.endswith(".heldout-pointer")
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


def _pointer_path(source: Path) -> Path:
    if source.is_dir():
        return source.parent / f"{source.name}.heldout-pointer"
    return source.parent / f"{source.name}.heldout-pointer"


def _write_pointer(source: Path, payload: dict[str, Any]) -> Path:
    pointer_file = _pointer_path(source)
    pointer_file.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return pointer_file


def register_dataset(
    dataset: str, source_path: str | Path, *, budget_total: int = DEFAULT_HELDOUT_BUDGET
) -> dict[str, Any]:
    if budget_total <= 0:
        raise ValueError("budget_total must be positive.")

    source = Path(source_path).expanduser()
    if not source.exists():
        raise FileNotFoundError(source)

    verify_bootstrap()

    root = dataset_root(dataset)
    root.parent.mkdir(parents=True, exist_ok=True)
    if root.exists():
        raise FileExistsError(root)

    source_ref = source
    if source.is_dir():
        shutil.move(str(source), str(root))
    else:
        root.mkdir(parents=True, exist_ok=False)
        shutil.move(str(source), str(root / source.name))

    manifest = compute_manifest(root)
    write_manifest(root, manifest)
    _write_pointer(
        source_ref,
        {
            "dataset": dataset,
            "heldout_path": str(root),
            "manifest_sha256": manifest["manifest_sha256"],
            "registered_at": manifest["generated_at"],
        },
    )

    with tx() as con:
        con.execute(
            """
            INSERT INTO ver_heldout_budgets(
              dataset, heldout_path, manifest_sha256, budget_total, budget_used
            )
            VALUES(?,?,?,?,0)
            ON CONFLICT(dataset) DO UPDATE SET
              heldout_path = excluded.heldout_path,
              manifest_sha256 = excluded.manifest_sha256,
              budget_total = excluded.budget_total,
              budget_used = 0,
              registered_at = CURRENT_TIMESTAMP
            """,
            (dataset, str(root), manifest["manifest_sha256"], budget_total),
        )

    return {
        "ok": True,
        "dataset": dataset,
        "heldout_path": str(root),
        "manifest_sha256": manifest["manifest_sha256"],
        "budget_total": budget_total,
        "budget_used": 0,
        "files": manifest["files"],
        "pointer_file": str(_pointer_path(source_ref)),
    }


def list_datasets() -> list[dict[str, Any]]:
    verify_bootstrap()
    from verify_mcp.db import _connect

    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT dataset, heldout_path, manifest_sha256, budget_total, budget_used, registered_at
            FROM ver_heldout_budgets
            ORDER BY registered_at DESC, dataset ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        con.close()


def inspect_dataset(dataset: str) -> dict[str, Any]:
    verify_bootstrap()
    from verify_mcp.db import _connect

    con = _connect()
    try:
        row = con.execute(
            """
            SELECT dataset, heldout_path, manifest_sha256, budget_total, budget_used, registered_at
            FROM ver_heldout_budgets
            WHERE dataset = ?
            """,
            (dataset,),
        ).fetchone()
    finally:
        con.close()
    if row is None:
        raise KeyError(dataset)

    root = Path(row["heldout_path"])
    manifest = load_manifest(root)
    current_manifest = compute_manifest(root) if root.exists() else None
    return {
        "registration": dict(row),
        "manifest": manifest,
        "current_manifest_sha256": (
            None if current_manifest is None else current_manifest["manifest_sha256"]
        ),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m claudescientist.heldout")
    subparsers = parser.add_subparsers(dest="command", required=True)

    register_parser = subparsers.add_parser(
        "register",
        help="Register and move a held-out dataset.",
    )
    register_parser.add_argument("dataset")
    register_parser.add_argument("path")
    register_parser.add_argument("--budget-total", type=int, default=DEFAULT_HELDOUT_BUDGET)

    subparsers.add_parser("list", help="List registered held-out datasets.")

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect a registered held-out dataset.",
    )
    inspect_parser.add_argument("dataset")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "register":
            result = register_dataset(
                args.dataset,
                args.path,
                budget_total=args.budget_total,
            )
        elif args.command == "list":
            result = {"ok": True, "datasets": list_datasets()}
        else:
            result = {"ok": True, **inspect_dataset(args.dataset)}
        exit_code = 0
    except KeyError:
        result = {"ok": False, "error": "unknown_dataset", "dataset": args.dataset}
        exit_code = 1
    except Exception as exc:  # pragma: no cover - defensive CLI surface
        result = {"ok": False, "error": exc.__class__.__name__, "message": str(exc)}
        exit_code = 1
    print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
