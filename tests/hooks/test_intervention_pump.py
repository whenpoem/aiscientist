from __future__ import annotations

from __future__ import annotations

import importlib.util
from pathlib import Path

from cockpit.db import connect, ensure


def test_intervention_pump_drains_rows(workspace):
    ensure()
    con = connect()
    try:
        con.execute(
            "INSERT INTO cockpit_interventions(kind, target, payload) VALUES(?,?,?)",
            ("reject", "hyp_1", "user rejected this hypothesis"),
        )
        con.commit()
    finally:
        con.close()

    hook_path = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "intervention_pump.py"
    spec = importlib.util.spec_from_file_location("intervention_pump", hook_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    payload = module.drain()
    assert "user rejected this hypothesis" in payload

    con = connect()
    try:
        delivered = con.execute(
            "SELECT delivered_at FROM cockpit_interventions WHERE target = ?",
            ("hyp_1",),
        ).fetchone()
    finally:
        con.close()

    assert delivered is not None
    assert delivered[0] is not None
