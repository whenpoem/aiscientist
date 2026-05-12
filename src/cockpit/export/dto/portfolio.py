"""PortfolioReport: side-by-side comparison of sibling proof_skeletons.

Walks the proof_skeleton children of a proposition (the immediate
children, not the deep draft chain), enriches each with its
Bradley-Terry strength + confidence interval, and returns them as
ordered candidates. Markdown renderers stack them vertically; the
HTML renderer turns them into a flex-column layout so the user can
visually compare drafts.
"""

from __future__ import annotations

import math
import sqlite3

from claudescientist.runtime import connect_sqlite, now_utc_iso, state_db_path
from cockpit.export.dto.base import Report, ReportSection


def _connect() -> sqlite3.Connection:
    return connect_sqlite(state_db_path())


def _short(node_id: str) -> str:
    if "_" not in node_id:
        return node_id[:10]
    prefix, suffix = node_id.split("_", 1)
    return f"{prefix}_{suffix[:6]}"


def _fetch_skeletons(con: sqlite3.Connection, proposition_id: str) -> list[dict]:
    rows = con.execute(
        """
        SELECT n.node_id, n.text, n.state, n.created_at,
               b.strength, b.strength_var, b.n_comparisons, b.status AS bt_status
        FROM mem_nodes n
        LEFT JOIN mem_bt_ratings b ON b.node_id = n.node_id
        WHERE n.parent_id = ? AND n.kind = 'proof_skeleton'
        ORDER BY COALESCE(b.strength, 0) DESC, n.created_at ASC
        """,
        (proposition_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def build_portfolio(node_id: str) -> Report:
    """Assemble a PortfolioReport for the given proposition node."""
    con = _connect()
    try:
        prop_row = con.execute(
            "SELECT node_id, kind, text FROM mem_nodes WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        if prop_row is None:
            raise ValueError(f"unknown node: {node_id!r}")
        prop = dict(prop_row)
        if prop["kind"] != "proposition":
            raise ValueError(
                f"portfolio reports target propositions; got {prop['kind']!r}"
            )

        sections: list[ReportSection] = [
            ReportSection(
                key="proposition",
                title="Proposition",
                body=prop["text"],
            )
        ]

        skeletons = _fetch_skeletons(con, node_id)
        if not skeletons:
            sections.append(
                ReportSection(
                    key="status",
                    title="Status",
                    body=(
                        "No proof skeletons have been proposed under this "
                        "proposition yet."
                    ),
                )
            )
        else:
            for idx, skel in enumerate(skeletons, start=1):
                strength = skel.get("strength")
                variance = skel.get("strength_var")
                n = int(skel.get("n_comparisons") or 0)
                if strength is None or n <= 0:
                    bt_line = "BT: not yet ranked"
                else:
                    sd = math.sqrt(max(1e-6, float(variance or 1.0)))
                    bt_line = (
                        f"BT: {float(strength):+.3f} ± {1.96 * sd:.3f}  "
                        f"(n={n}, status={skel.get('bt_status') or 'active'})"
                    )
                lines = [
                    f"candidate id: {skel['node_id']}",
                    f"state: {skel['state']}",
                    bt_line,
                    "",
                    skel["text"],
                ]
                sections.append(
                    ReportSection(
                        key=f"candidate_{idx}",
                        title=f"Candidate {idx} ({_short(skel['node_id'])})",
                        body="\n".join(lines),
                        meta={
                            "candidate_id": skel["node_id"],
                            "rank": idx,
                            "strength": strength,
                            "n_comparisons": n,
                        },
                    )
                )
    finally:
        con.close()

    title = f"Portfolio: {_short(node_id)}"
    return Report(
        kind="portfolio",
        node_id=node_id,
        title=title,
        generated_at=now_utc_iso(),
        sections=tuple(sections),
        metadata={"candidate_count": len(sections) - 1},
    )
