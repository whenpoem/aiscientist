"""Provenance, pin, and refresh tools.

Owns ``ver_provenance``, ``ver_metric_pins`` and ``ver_provenance_dag``.
``pin_metric`` lives here because it shares ``_insert_provenance`` with
``record_provenance``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from verify_mcp.db import _connect, tx
from verify_mcp.provenance import normalize_claim, normalize_value
from verify_mcp.run_manifest import (
    capture_run_manifest,
    hash_file,
    refresh_run_manifest,
    store_run_manifest,
)

from ._common import _emit_event


def _hash_file(path: Path) -> str | None:
    return hash_file(path)


def _compute_input_hashes(input_files: list[str] | None) -> list[dict[str, str | None]]:
    if not input_files:
        return []
    hashes: list[dict[str, str | None]] = []
    for raw in input_files:
        path = Path(str(raw)).expanduser()
        hashes.append({"path": str(path), "sha256": _hash_file(path)})
    return hashes


def _record_provenance_dag(
    con,
    *,
    prov_id: int,
    input_files: list[str] | None,
    parent_prov_ids: list[int] | None,
) -> dict:
    input_hashes = _compute_input_hashes(input_files)
    output_seed = "|".join(
        f"{entry.get('path','')}::{entry.get('sha256') or ''}" for entry in input_hashes
    )
    output_hash = (
        hashlib.sha256(output_seed.encode("utf-8")).hexdigest() if input_hashes else ""
    )
    con.execute(
        """
        INSERT INTO ver_provenance_dag(
          prov_id, input_hashes, output_hash, parent_prov_ids, stale, refreshed_at
        )
        VALUES(?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
        ON CONFLICT(prov_id) DO UPDATE SET
          input_hashes = excluded.input_hashes,
          output_hash = excluded.output_hash,
          parent_prov_ids = excluded.parent_prov_ids,
          stale = 0,
          refreshed_at = CURRENT_TIMESTAMP
        """,
        (
            int(prov_id),
            json.dumps(input_hashes, ensure_ascii=True),
            output_hash,
            json.dumps([int(pid) for pid in (parent_prov_ids or [])], ensure_ascii=True),
        ),
    )
    return {
        "prov_id": int(prov_id),
        "input_hashes": input_hashes,
        "output_hash": output_hash,
    }


def _empty_seed_summary() -> dict:
    return {
        "seed_verdict": "missing",
        "seed_run_count": 0,
        "seed_suite_count": 0,
        "stable_seed_runs": 0,
        "stable_seed_suites": 0,
        "latest_seed_run_id": None,
        "latest_seed_count": 0,
        "seed_runs": [],
    }


def _seed_summaries_for_pins(con, pin_ids: list[int]) -> dict[int, dict]:
    if not pin_ids:
        return {}
    placeholders = ",".join("?" for _ in pin_ids)
    rows = con.execute(
        f"""
        SELECT run_id, metric_pin_id, seeds_json, values_json, mean_value,
               std_value, verdict, created_at
        FROM ver_seed_runs
        WHERE metric_pin_id IN ({placeholders})
        ORDER BY created_at DESC, run_id DESC
        """,
        tuple(pin_ids),
    ).fetchall()
    summaries = {pin_id: _empty_seed_summary() for pin_id in pin_ids}
    for row in rows:
        pin_id = int(row["metric_pin_id"])
        summary = summaries.setdefault(pin_id, _empty_seed_summary())
        try:
            seeds = json.loads(row["seeds_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            seeds = []
        seed_count = len(seeds) if isinstance(seeds, list) else 0
        run = {
            "run_id": int(row["run_id"]),
            "verdict": row["verdict"],
            "mean_value": float(row["mean_value"]),
            "std_value": float(row["std_value"]),
            "seed_count": seed_count,
            "created_at": row["created_at"],
        }
        summary["seed_suite_count"] += 1
        summary["seed_run_count"] += seed_count
        if row["verdict"] == "stable":
            summary["stable_seed_suites"] += 1
            summary["stable_seed_runs"] += seed_count
        if summary["latest_seed_run_id"] is None:
            summary["latest_seed_run_id"] = int(row["run_id"])
            summary["seed_verdict"] = row["verdict"]
            summary["latest_seed_count"] = seed_count
        if len(summary["seed_runs"]) < 5:
            summary["seed_runs"].append(run)
    return summaries


def record_provenance(
    claim: str,
    value: str,
    session_id: str,
    source_command: str = "",
    input_files: list[str] | None = None,
    parent_prov_ids: list[int] | None = None,
    config_files: list[str] | None = None,
) -> dict:
    """Store provenance for a numeric claim.

    When ``input_files`` is provided each path is hashed (sha256) and the
    resulting fingerprint is stored in ``ver_provenance_dag`` so the chain
    can later be re-validated by :func:`refresh_claim`.
    """
    manifest = capture_run_manifest(
        command=source_command,
        input_files=input_files,
        config_files=config_files,
    )
    manifest_files = [str(entry["path"]) for entry in manifest["files"]]
    with tx() as con:
        cur = con.execute(
            """
            INSERT INTO ver_provenance(claim, value, session_id, source_command)
            VALUES(?,?,?,?)
            """,
            (normalize_claim(claim), normalize_value(str(value)), session_id, source_command),
        )
        provenance_id = int(cur.lastrowid)
        dag = _record_provenance_dag(
            con,
            prov_id=provenance_id,
            input_files=manifest_files,
            parent_prov_ids=parent_prov_ids,
        )
        stored_manifest = store_run_manifest(
            con,
            manifest,
            provenance_id=provenance_id,
        )
    return {
        "recorded": True,
        "provenance_id": provenance_id,
        "dag": dag,
        "run_manifest": stored_manifest,
    }


def pin_metric(
    claim: str,
    value: str,
    session_id: str,
    source_command: str = "",
    note: str = "",
    input_files: list[str] | None = None,
    parent_prov_ids: list[int] | None = None,
    config_files: list[str] | None = None,
) -> dict:
    """Pin a central metric to a provenance record for later write-up checks."""
    normalized_claim = normalize_claim(claim)
    normalized_value = normalize_value(value)
    manifest = capture_run_manifest(
        command=source_command,
        input_files=input_files,
        config_files=config_files,
    )
    manifest_files = [str(entry["path"]) for entry in manifest["files"]]
    with tx() as con:
        cur = con.execute(
            """
            INSERT INTO ver_provenance(claim, value, session_id, source_command)
            VALUES(?,?,?,?)
            """,
            (normalized_claim, normalized_value, session_id, source_command),
        )
        provenance_id = int(cur.lastrowid)
        pin = con.execute(
            """
            INSERT INTO ver_metric_pins(
                claim, value, provenance_id, session_id, source_command, note
            )
            VALUES(?,?,?,?,?,?)
            """,
            (
                normalized_claim,
                normalized_value,
                provenance_id,
                session_id,
                source_command,
                note.strip(),
            ),
        )
        pin_id = int(pin.lastrowid)
        dag = _record_provenance_dag(
            con,
            prov_id=provenance_id,
            input_files=manifest_files,
            parent_prov_ids=parent_prov_ids,
        )
        stored_manifest = store_run_manifest(
            con,
            manifest,
            provenance_id=provenance_id,
        )
        _emit_event(
            con,
            "claim_pinned",
            {
                "pin_id": pin_id,
                "claim": normalized_claim,
                "value": normalized_value,
                "session_id": session_id,
            },
        )
    return {
        "pinned": True,
        "pin_id": pin_id,
        "provenance_id": provenance_id,
        "dag": dag,
        "run_manifest": stored_manifest,
    }


def check_provenance(claim: str) -> dict:
    """Return the latest provenance evidence for a claim."""
    normalized_claim = normalize_claim(claim)
    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT id, claim, value, session_id, source_command, created_at
            FROM ver_provenance
            WHERE claim = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 20
            """,
            (normalized_claim,),
        ).fetchall()
        pins = con.execute(
            """
            SELECT id, claim, value, provenance_id, session_id, source_command, note, created_at
            FROM ver_metric_pins
            WHERE claim = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 20
            """,
            (normalized_claim,),
        ).fetchall()
        if not rows:
            return {"status": "missing"}
        pin_dicts = [dict(pin) for pin in pins]
        seed_summaries = _seed_summaries_for_pins(
            con,
            [int(pin["id"]) for pin in pin_dicts],
        )
        for pin in pin_dicts:
            pin["pin_id"] = int(pin["id"])
            pin.update(seed_summaries.get(int(pin["id"]), _empty_seed_summary()))
        manifests = con.execute(
            """
            SELECT m.manifest_id, m.provenance_id, m.seed_run_id,
                   m.manifest_sha256, m.manifest_json, m.created_at
            FROM ver_run_manifests m
            JOIN ver_provenance p ON p.id = m.provenance_id
            WHERE p.claim = ?
            ORDER BY m.created_at DESC, m.manifest_id DESC
            LIMIT 20
            """,
            (normalized_claim,),
        ).fetchall()
        return {
            "status": "found",
            "evidence": [dict(row) for row in rows],
            "pins": pin_dicts,
            "run_manifests": [dict(row) for row in manifests],
        }
    finally:
        con.close()


def refresh_claim(claim: str) -> dict:
    """Walk ``ver_provenance_dag`` for a claim and re-hash recorded inputs.

    Returns the chain of provenance rows attached to the claim with each
    row's stale flag re-evaluated. Stale rows emit ``prov_dag_stale`` events.
    """
    normalized_claim = normalize_claim(claim)
    affected: list[dict] = []
    with tx() as con:
        rows = con.execute(
            """
            SELECT p.id AS prov_id, p.claim, p.value, p.session_id, p.source_command,
                   d.input_hashes, d.output_hash, d.parent_prov_ids, d.stale,
                   d.refreshed_at
            FROM ver_provenance p
            LEFT JOIN ver_provenance_dag d ON d.prov_id = p.id
            WHERE p.claim = ?
            ORDER BY p.created_at DESC, p.id DESC
            """,
            (normalized_claim,),
        ).fetchall()
        if not rows:
            return {"status": "missing", "claim": normalized_claim, "checked": []}

        for row in rows:
            prov_id = int(row["prov_id"])
            stored_raw = row["input_hashes"]
            if stored_raw is None:
                affected.append(
                    {
                        "prov_id": prov_id,
                        "stale": False,
                        "unchecked": True,
                        "reason": "no_dag_entry",
                    }
                )
                continue
            try:
                stored = json.loads(stored_raw)
            except (TypeError, json.JSONDecodeError):
                stored = []

            mismatched: list[dict[str, str | None]] = []
            for entry in stored:
                path = Path(str(entry.get("path", "")))
                expected = entry.get("sha256")
                actual = _hash_file(path) if str(path) else None
                if expected != actual:
                    mismatched.append(
                        {
                            "path": str(path),
                            "expected": expected,
                            "actual": actual,
                        }
                    )

            manifest_rows = con.execute(
                """
                SELECT manifest_id, manifest_json
                FROM ver_run_manifests
                WHERE provenance_id = ?
                ORDER BY manifest_id
                """,
                (prov_id,),
            ).fetchall()
            manifest_mismatched: list[dict] = []
            for manifest_row in manifest_rows:
                try:
                    manifest = json.loads(manifest_row["manifest_json"])
                except (TypeError, json.JSONDecodeError):
                    manifest_mismatched.append(
                        {
                            "manifest_id": int(manifest_row["manifest_id"]),
                            "field": "manifest_json",
                            "error": "invalid_json",
                        }
                    )
                    continue
                for mismatch in refresh_run_manifest(manifest):
                    manifest_mismatched.append(
                        {"manifest_id": int(manifest_row["manifest_id"]), **mismatch}
                    )

            stale = 1 if (mismatched or manifest_mismatched) else 0
            con.execute(
                """
                UPDATE ver_provenance_dag
                SET stale = ?, refreshed_at = CURRENT_TIMESTAMP
                WHERE prov_id = ?
                """,
                (stale, prov_id),
            )
            if stale:
                _emit_event(
                    con,
                    "prov_dag_stale",
                    {
                        "prov_id": prov_id,
                        "claim": normalized_claim,
                        "mismatched": mismatched,
                        "manifest_mismatched": manifest_mismatched,
                    },
                )
            affected.append(
                {
                    "prov_id": prov_id,
                    "stale": bool(stale),
                    "unchecked": False,
                    "mismatched": mismatched,
                    "manifest_mismatched": manifest_mismatched,
                    "input_count": len(stored),
                    "manifest_count": len(manifest_rows),
                }
            )

    stale_count = sum(1 for entry in affected if entry.get("stale"))
    unchecked_count = sum(1 for entry in affected if entry.get("unchecked"))
    return {
        "status": "stale" if stale_count else "fresh",
        "claim": normalized_claim,
        "checked": affected,
        "stale_count": stale_count,
        "unchecked_count": unchecked_count,
    }
