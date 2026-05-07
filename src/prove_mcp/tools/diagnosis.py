"""Snippet-level diagnosis (P3).

The diagnostic loop runs three atomic tools, in any order the main agent
chooses (ADR 0007 layering doctrine):

1. ``diagnose_snippet(snippet_id, k=5)`` -- read-only. Fetches the
   snippet text and runs ``memory_mcp.match_signatures`` with
   ``domain='proof'`` to surface the top-k historical proof errors that
   resemble this snippet. Returns the candidates plus a structured
   diagnosis prompt the agent can feed to its judging model. No state
   mutation.

2. ``register_diagnosis(...)`` -- append-write. The agent has reasoned
   over the candidates and decided whether the snippet contains a flaw.
   This tool appends an entry to the manifest's ``items_json``.

3. ``finalize_manifest(manifest_id)`` -- closes diagnosis. If no entry
   has ``is_flawed=True`` the manifest moves to ``empty``; otherwise it
   stays ``open`` and the correction stage takes over.

This split keeps the LLM call out of the MCP layer (verbs are atomic;
LLM orchestration belongs to the agent loop).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from claudescientist.runtime import now_utc_iso
from prove_mcp.db import _connect, tx

from ._common import _emit_event


def _load_manifest(con: sqlite3.Connection, manifest_id: int) -> dict[str, Any]:
    row = con.execute(
        "SELECT manifest_id, draft_id, status, items_json, created_at, finalized_at "
        "FROM prv_diagnostic_manifests WHERE manifest_id = ?",
        (manifest_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown manifest: {manifest_id}")
    return dict(row)


def diagnose_snippet(snippet_id: str, k: int = 5) -> dict:
    """Return historical proof-domain failures resembling this snippet.

    Performs a cross-domain failure-ledger search restricted to
    ``domain='proof'``. The returned ``candidates`` are exactly what
    ``memory_mcp.match_signatures`` would yield. The accompanying
    ``prompt`` field is a ready-to-evaluate diagnostic prompt the main
    agent can feed to its judging model.
    """
    k = max(1, min(int(k), 25))
    con = _connect()
    try:
        snip = con.execute(
            """
            SELECT node_id, kind, text, state, parent_id
            FROM mem_nodes
            WHERE node_id = ?
            """,
            (snippet_id,),
        ).fetchone()
    finally:
        con.close()
    if snip is None:
        raise ValueError(f"Unknown snippet: {snippet_id}")
    if snip["kind"] != "proof_snippet":
        raise ValueError(
            f"diagnose_snippet expects a proof_snippet node; got kind={snip['kind']!r}"
        )

    # Lazy-import the cross-trunk public API; module-level import is
    # forbidden by the prove_mcp/__init__.py "Do NOT" list.
    from memory_mcp.impl import match_signatures

    candidates = match_signatures(snip["text"], k=k, domain="proof")

    prompt_lines = [
        "You are auditing one snippet of a statistical proof draft.",
        "Decide whether the snippet contains a logical flaw, an unjustified",
        "step, or a missing assumption. The candidates below are historical",
        "proof errors retrieved from the failure ledger that share signatures",
        "with this snippet -- treat each as a potential match, not a verdict.",
        "",
        "Snippet:",
        "---",
        snip["text"],
        "---",
        "",
        f"Top-{len(candidates)} similar historical proof errors:",
    ]
    for i, cand in enumerate(candidates, start=1):
        prompt_lines.append(
            f"  {i}. id={cand['failure_id']} | trigger: {cand['trigger']!r} | "
            f"symptom: {cand['symptom']!r} | resolution: {cand['resolution']!r}"
        )
    prompt_lines.extend(
        [
            "",
            "Return strict JSON: {",
            '  "is_flawed": bool,',
            '  "description": "<one-sentence reason>",',
            '  "matched_failure_ids": [<int>, ...]   # subset of candidate ids you cite',
            "}",
        ]
    )
    return {
        "snippet_id": snippet_id,
        "snippet_text": snip["text"],
        "candidates": candidates,
        "prompt": "\n".join(prompt_lines),
    }


def register_diagnosis(
    manifest_id: int,
    snippet_id: str,
    is_flawed: bool,
    description: str,
    matched_failure_ids: list[int] | None = None,
) -> dict:
    """Append one diagnosis entry to a manifest.

    The manifest's ``status`` stays ``'open'`` until
    :func:`finalize_manifest` is called. Calling ``register_diagnosis``
    on an already-finalised manifest raises -- corrections require a
    fresh manifest (which segment_proof creates automatically when the
    agent re-segments a corrected draft).
    """
    description = (description or "").strip()
    if not description:
        raise ValueError("description must be non-empty")
    with tx() as con:
        manifest = _load_manifest(con, manifest_id)
        if manifest["status"] != "open":
            raise ValueError(
                f"manifest {manifest_id} status is {manifest['status']!r}; "
                "register_diagnosis only allowed while status='open'"
            )
        # Verify snippet exists and belongs to the manifest's draft.
        snip = con.execute(
            "SELECT node_id, kind, parent_id FROM mem_nodes WHERE node_id = ?",
            (snippet_id,),
        ).fetchone()
        if snip is None:
            raise ValueError(f"Unknown snippet: {snippet_id}")
        if snip["kind"] != "proof_snippet":
            raise ValueError(f"node {snippet_id} is not a proof_snippet")
        if snip["parent_id"] != manifest["draft_id"]:
            raise ValueError(
                f"snippet {snippet_id} does not belong to draft {manifest['draft_id']}"
            )
        try:
            payload = json.loads(manifest["items_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        entries = list(payload.get("entries") or [])
        entries.append(
            {
                "snippet_id": snippet_id,
                "is_flawed": bool(is_flawed),
                "description": description,
                "matched_failure_ids": [int(x) for x in (matched_failure_ids or [])],
                "recorded_at": now_utc_iso(),
            }
        )
        payload["entries"] = entries
        con.execute(
            "UPDATE prv_diagnostic_manifests SET items_json = ? WHERE manifest_id = ?",
            (json.dumps(payload), manifest_id),
        )
        _emit_event(
            con,
            "proof_diagnosis_recorded",
            {
                "manifest_id": manifest_id,
                "snippet_id": snippet_id,
                "is_flawed": bool(is_flawed),
                "draft_id": manifest["draft_id"],
            },
        )
    return {"manifest_id": manifest_id, "entry_count": len(entries)}


def finalize_manifest(manifest_id: int) -> dict:
    """Close diagnosis: ``empty`` if no flawed entries, else stays ``open``.

    Idempotent within a status. Re-calling on an already-empty manifest
    returns the cached status; calling on an applied manifest raises so
    the caller cannot accidentally roll back history.
    """
    with tx() as con:
        manifest = _load_manifest(con, manifest_id)
        if manifest["status"] == "applied":
            raise ValueError(
                f"manifest {manifest_id} already applied; cannot re-finalise"
            )
        try:
            payload = json.loads(manifest["items_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        entries = payload.get("entries") or []
        any_flawed = any(bool(e.get("is_flawed")) for e in entries)
        new_status = "open" if any_flawed else "empty"
        if manifest["status"] != new_status:
            con.execute(
                """
                UPDATE prv_diagnostic_manifests
                SET status = ?, finalized_at = CURRENT_TIMESTAMP
                WHERE manifest_id = ?
                """,
                (new_status, manifest_id),
            )
            _emit_event(
                con,
                "proof_diagnosis_complete",
                {
                    "manifest_id": manifest_id,
                    "draft_id": manifest["draft_id"],
                    "status": new_status,
                    "flawed_count": sum(1 for e in entries if e.get("is_flawed")),
                    "entry_count": len(entries),
                },
            )
    return {
        "manifest_id": manifest_id,
        "status": new_status,
        "flawed_count": sum(1 for e in entries if e.get("is_flawed")),
        "entry_count": len(entries),
    }


def list_diagnostic_manifests(
    draft_id: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """Browse manifests filtered by draft and/or status."""
    if status is not None and status not in {"open", "empty", "applied"}:
        raise ValueError(
            f"status filter must be open|empty|applied; got {status!r}"
        )
    con = _connect()
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if draft_id is not None:
            clauses.append("draft_id = ?")
            params.append(draft_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = con.execute(
            f"""
            SELECT manifest_id, draft_id, status, items_json, created_at, finalized_at
            FROM prv_diagnostic_manifests
            {where}
            ORDER BY manifest_id DESC
            """,
            tuple(params),
        ).fetchall()
    finally:
        con.close()
    out: list[dict] = []
    for row in rows:
        try:
            payload = json.loads(row["items_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        entries = payload.get("entries") or []
        out.append(
            {
                "manifest_id": row["manifest_id"],
                "draft_id": row["draft_id"],
                "status": row["status"],
                "entry_count": len(entries),
                "flawed_count": sum(1 for e in entries if e.get("is_flawed")),
                "entries": entries,
                "created_at": row["created_at"],
                "finalized_at": row["finalized_at"],
            }
        )
    return out
