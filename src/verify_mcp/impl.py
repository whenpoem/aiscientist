"""Tool implementations for verify_mcp."""

from __future__ import annotations

from .db import _connect, bootstrap, tx
from .leakage import scan_file, scan_python

TOOL_NAMES = ["leakage_check", "record_provenance", "check_provenance"]


def leakage_check(script_path: str | None = None, script_text: str | None = None) -> dict:
    """Run the leakage detector against a file path or raw script text."""
    if bool(script_path) == bool(script_text):
        raise ValueError("Provide exactly one of script_path or script_text.")
    findings = scan_file(script_path) if script_path else scan_python(script_text or "")
    return {"clean": len(findings) == 0, "findings": [finding.to_dict() for finding in findings]}


def record_provenance(claim: str, value: str, session_id: str, source_command: str = "") -> dict:
    """Store provenance for a numeric claim."""
    with tx() as con:
        con.execute(
            """
            INSERT INTO ver_provenance(claim, value, session_id, source_command)
            VALUES(?,?,?,?)
            """,
            (claim, str(value), session_id, source_command),
        )
    return {"recorded": True}


def check_provenance(claim: str) -> dict:
    """Return the latest provenance evidence for a claim."""
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
            (claim,),
        ).fetchall()
        if not rows:
            return {"status": "missing"}
        return {"status": "found", "evidence": [dict(row) for row in rows]}
    finally:
        con.close()


bootstrap()

