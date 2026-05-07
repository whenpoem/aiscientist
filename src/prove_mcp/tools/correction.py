"""Delayed global correction tools (P3).

The agent reads ``compose_correction_prompt`` to build a single prompt
that ties the full draft to every flawed snippet's diagnosis. It then
generates a corrected LaTeX draft and calls :func:`apply_correction` to:

- persist the corrected text as a new ``proof_skeleton`` revision
  (a child of the original draft, mirroring revision history through
  the parent chain)
- mark the manifest ``status='applied'`` so it cannot be re-edited
- emit a cockpit event so the TUI shows the correction landing
"""

from __future__ import annotations

import json

from prove_mcp.db import _connect, tx

from ._common import _emit_event
from .diagnosis import _load_manifest
from .nodes import _insert_node, _new_id


def compose_correction_prompt(draft_id: str, manifest_id: int) -> dict:
    """Build the prompt used to produce a globally corrected draft.

    Pure read. Assembles draft text + all flawed entries from the
    manifest into one prompt; the agent fills it externally.
    """
    con = _connect()
    try:
        draft = con.execute(
            "SELECT node_id, kind, text FROM mem_nodes WHERE node_id = ?",
            (draft_id,),
        ).fetchone()
        if draft is None:
            raise ValueError(f"Unknown draft: {draft_id}")
        if draft["kind"] != "proof_skeleton":
            raise ValueError(
                f"compose_correction_prompt expects a proof_skeleton draft; "
                f"got kind={draft['kind']!r}"
            )
        manifest_row = con.execute(
            "SELECT manifest_id, draft_id, status, items_json "
            "FROM prv_diagnostic_manifests WHERE manifest_id = ?",
            (manifest_id,),
        ).fetchone()
        if manifest_row is None:
            raise ValueError(f"Unknown manifest: {manifest_id}")
        if manifest_row["draft_id"] != draft_id:
            raise ValueError(
                f"manifest {manifest_id} belongs to draft "
                f"{manifest_row['draft_id']!r}, not {draft_id!r}"
            )
    finally:
        con.close()
    try:
        payload = json.loads(manifest_row["items_json"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    flawed = [e for e in (payload.get("entries") or []) if e.get("is_flawed")]
    lines = [
        "You are correcting a statistical proof draft. Every flawed snippet",
        "below has already been diagnosed by the snippet-level audit. Apply",
        "ALL corrections in one pass and return a complete revised LaTeX",
        "proof; do not patch only some of the issues.",
        "",
        "Original draft:",
        "---",
        draft["text"],
        "---",
        "",
        f"Flawed snippets ({len(flawed)} total):",
    ]
    for i, entry in enumerate(flawed, start=1):
        lines.append(
            f"  {i}. snippet {entry.get('snippet_id')!r} -- "
            f"{entry.get('description', '')}"
        )
        ids = entry.get("matched_failure_ids") or []
        if ids:
            lines.append(f"     historical failures cited: {ids}")
    lines.extend(
        [
            "",
            "Return the full corrected LaTeX proof. No commentary, no diff,",
            "no surrounding prose. Just the proof.",
        ]
    )
    return {
        "draft_id": draft_id,
        "manifest_id": manifest_id,
        "manifest_status": manifest_row["status"],
        "flawed_count": len(flawed),
        "prompt": "\n".join(lines),
    }


def apply_correction(
    draft_id: str,
    manifest_id: int,
    corrected_text: str,
    note: str = "",
) -> dict:
    """Persist a corrected draft and close the manifest as ``applied``.

    Creates a new proof_skeleton mem_node carrying ``corrected_text``,
    parented to ``draft_id`` so the revision chain is preserved. Marks
    the manifest ``status='applied'``. Idempotency is delegated to the
    caller -- re-calling with the same args creates a second revision.
    """
    if not (corrected_text or "").strip():
        raise ValueError("corrected_text must be non-empty")
    new_id = _new_id("proof_skeleton")
    with tx() as con:
        manifest = _load_manifest(con, manifest_id)
        if manifest["status"] == "applied":
            raise ValueError(
                f"manifest {manifest_id} already applied; segment a fresh "
                "draft if further corrections are needed"
            )
        if manifest["draft_id"] != draft_id:
            raise ValueError(
                f"manifest {manifest_id} belongs to draft "
                f"{manifest['draft_id']!r}, not {draft_id!r}"
            )
        draft = con.execute(
            "SELECT node_id, kind FROM mem_nodes WHERE node_id = ?",
            (draft_id,),
        ).fetchone()
        if draft is None:
            raise ValueError(f"Unknown draft: {draft_id}")
        if draft["kind"] != "proof_skeleton":
            raise ValueError(
                f"apply_correction expects a proof_skeleton draft; "
                f"got kind={draft['kind']!r}"
            )
        _insert_node(
            con,
            node_id=new_id,
            kind="proof_skeleton",
            text=corrected_text,
            parent_id=draft_id,
        )
        con.execute(
            """
            UPDATE prv_diagnostic_manifests
            SET status = 'applied', finalized_at = CURRENT_TIMESTAMP
            WHERE manifest_id = ?
            """,
            (manifest_id,),
        )
        _emit_event(
            con,
            "proof_correction_applied",
            {
                "manifest_id": manifest_id,
                "old_draft_id": draft_id,
                "new_draft_id": new_id,
                "note": note,
            },
        )
    return {
        "new_draft_id": new_id,
        "old_draft_id": draft_id,
        "manifest_id": manifest_id,
        "manifest_status": "applied",
    }
