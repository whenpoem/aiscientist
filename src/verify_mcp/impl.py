"""Tool implementations for verify_mcp."""

from __future__ import annotations

from .db import _connect, bootstrap, tx
from .leakage import scan_file, scan_python
from .provenance import normalize_claim, normalize_value

TOOL_NAMES = ["leakage_check", "record_provenance", "check_provenance", "pin_metric"]


def _insert_provenance(
    *,
    claim: str,
    value: str,
    session_id: str,
    source_command: str,
) -> int:
    with tx() as con:
        cur = con.execute(
            """
            INSERT INTO ver_provenance(claim, value, session_id, source_command)
            VALUES(?,?,?,?)
            """,
            (normalize_claim(claim), normalize_value(value), session_id, source_command),
        )
        return int(cur.lastrowid)


def leakage_check(script_path: str | None = None, script_text: str | None = None) -> dict:
    """Run the leakage detector against a file path or raw script text."""
    if bool(script_path) == bool(script_text):
        raise ValueError("Provide exactly one of script_path or script_text.")
    findings = scan_file(script_path) if script_path else scan_python(script_text or "")
    return {"clean": len(findings) == 0, "findings": [finding.to_dict() for finding in findings]}


def record_provenance(claim: str, value: str, session_id: str, source_command: str = "") -> dict:
    """Store provenance for a numeric claim."""
    provenance_id = _insert_provenance(
        claim=claim,
        value=str(value),
        session_id=session_id,
        source_command=source_command,
    )
    return {"recorded": True, "provenance_id": provenance_id}


def pin_metric(
    claim: str,
    value: str,
    session_id: str,
    source_command: str = "",
    note: str = "",
) -> dict:
    """Pin a central metric to a provenance record for later write-up checks."""
    normalized_claim = normalize_claim(claim)
    normalized_value = normalize_value(value)
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
    return {"pinned": True, "pin_id": int(pin.lastrowid), "provenance_id": provenance_id}


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
        return {
            "status": "found",
            "evidence": [dict(row) for row in rows],
            "pins": [dict(pin) for pin in pins],
        }
    finally:
        con.close()


bootstrap()
