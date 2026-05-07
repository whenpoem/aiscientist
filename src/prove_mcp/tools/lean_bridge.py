"""Lean reinsurance bridge (P4).

Three atomic tools, no implicit cross-trunk side effects (per ADR 0007):

- ``triage_for_formalization(proposition_id)`` -- pure read. Decides whether
  a proposition is small + closed enough to be worth attempting in Lean
  via the third-party ``lean-lsp-mcp`` server. Cheap heuristic;
  agents may override.

- ``record_lean_attempt(...)`` -- pure write to ``prv_lean_attempts``. The
  agent owns the actual lean-lsp-mcp calls and decides what status to
  write. Cross-trunk attachments (attach_evidence on success,
  record_failure on failure) are the agent's job, not this tool's, so
  the audit trail in prv_lean_attempts stays decoupled.

- ``list_lean_attempts(...)`` -- browse.

Triage rules
------------
A proposition is ``eligible`` iff:

1. text length is in [10, 600] characters
2. at least one whitelist keyword fires (the lemma is in mathlib's
   statistical comfort zone)
3. no blacklist keyword fires (continuous-measure-theory or
   functional-analytic constructions that mathlib has not formalised)

The whitelist + blacklist are kept small and declarative; difficulty is
``low`` for short whitelisted propositions, ``med`` otherwise.
"""

from __future__ import annotations

import json
from typing import Any

from prove_mcp.db import _connect, tx

from ._common import _emit_event

VALID_STATUS = {"queued", "running", "verified", "failed", "timeout"}
# Difficulty buckets only apply to eligible propositions. Ineligible ones
# get 'n/a' so downstream consumers can distinguish "rejected by triage" from
# "eligible but expected to be hard". 'unknown' remains for legacy callers
# that record_lean_attempt without passing a triage payload.
VALID_DIFFICULTY = {"low", "med", "high", "n/a", "unknown"}

_WHITELIST = {
    # Probability inequalities (mathlib-friendly).
    "markov",
    "chebyshev",
    "cauchy-schwarz",
    "cauchy schwarz",
    "jensen",
    "holder",
    "hoeffding",
    "bernstein",
    "bonferroni",
    "union bound",
    "mcdiarmid",
    # Borel-Cantelli + zero-one laws.
    "borel-cantelli",
    "borel cantelli",
    # Convergence theorems (mathlib has these).
    "central limit",
    "law of large numbers",
    "lindeberg",
    "slutsky",
    "continuous mapping",
    "delta method",
    "donsker",
    "glivenko-cantelli",
    "glivenko cantelli",
    "portmanteau",
    "skorokhod",
    "characteristic function",
    "levy",
    # Concentration / tails.
    "concentration",
    "tail bound",
    "sub-gaussian",
    "subgaussian",
    "sub-exponential",
    "subexponential",
    "azuma",
    # Estimation theory.
    "expectation",
    "variance",
    "covariance",
    "correlation",
    "moment",
    "independent",
    "iid",
    "sample mean",
    "sample variance",
    "unbiased",
    "estimator",
    "linearity",
    "rao-blackwell",
    "rao blackwell",
    "lehmann-scheffe",
    "lehmann scheffe",
    "fisher information",
    "cramer-rao",
    "cramer rao",
    "score function",
    "mle",
    "maximum likelihood",
    "consistency",
    "asymptotic normality",
    "asymptotic efficiency",
    "sufficient",
    "sufficiency",
    "ancillary",
    "basu",
    # Hypothesis testing.
    "neyman-pearson",
    "neyman pearson",
    "likelihood ratio",
    "wald test",
    "score test",
    "lr test",
    "uniformly most powerful",
    "ump",
    "monotone likelihood ratio",
    "karlin-rubin",
    "p-value",
    "p value",
    # Bayes.
    "bayes",
    "posterior",
    "conjugate",
    "bernstein-von mises",
    "bernstein von mises",
    # Regression.
    "regression",
    "gauss-markov",
    "gauss markov",
    "blue",
    "leverage",
    "hat matrix",
    "homoskedastic",
    # Information theory.
    "kl divergence",
    "kullback-leibler",
    "kullback leibler",
    "pinsker",
    "fano",
    "data processing",
    "entropy",
    # Distributions / common settings.
    "binomial",
    "poisson",
    "gaussian",
    "normal distribution",
    "bernoulli",
}

_BLACKLIST = {
    # Functional-analytic objects mathlib has but stat-proofs rarely need;
    # appearance signals an out-of-scope abstraction level.
    "banach",
    "hilbert",
    "frechet",
    "sobolev",
    "operator algebra",
    "infinite-dimensional",
    "infinite dimensional",
    # Stochastic processes / SDEs — mathlib coverage is genuinely thin.
    "stochastic differential",
    "brownian motion",
    "ito calculus",
    "ito's lemma",
    "ito formula",
    # NOTE: removed 'lebesgue integral', 'ergodic', 'measure-preserving' from
    # earlier blacklist - mathlib has them. They were over-aggressive.
}

# Whitelist tokens that need word-boundary protection because their substring
# also appears inside common English words. E.g. 'ols' is inside 'controls',
# 'tools'; 'mle' could appear inside an arbitrary word; 'rao' inside 'narrate'.
# These are matched with re word-boundary instead of plain substring.
_WORD_BOUNDARY_REQUIRED = {"ols", "mle", "rao", "ump", "blue", "ito"}


def _normalize_for_keywords(text: str) -> str:
    return (text or "").lower()


def _keyword_hits(text: str, vocab: set[str]) -> list[str]:
    """Return sorted list of vocab keywords that appear in text.

    Most keywords match by simple substring (covers multi-word terms like
    "central limit" cleanly). Tokens listed in ``_WORD_BOUNDARY_REQUIRED``
    use a regex word-boundary check so they don't false-positive on words
    like ``controls`` (which contains the substring ``ols``).
    """
    import re as _re
    haystack = _normalize_for_keywords(text)
    hits: set[str] = set()
    for kw in vocab:
        if kw in _WORD_BOUNDARY_REQUIRED:
            if _re.search(rf"\b{_re.escape(kw)}\b", haystack):
                hits.add(kw)
        elif kw in haystack:
            hits.add(kw)
    return sorted(hits)


def triage_for_formalization(proposition_id: str) -> dict[str, Any]:
    """Decide whether to send this proposition to the prover agent.

    Returns ``{eligible, reasons, estimated_difficulty, whitelist_hits,
    blacklist_hits, length}``. The agent inspects ``eligible`` and
    spawns the prover only if True. ``reasons`` is a human-readable
    list of strings explaining the decision.
    """
    con = _connect()
    try:
        row = con.execute(
            "SELECT node_id, kind, text FROM mem_nodes WHERE node_id = ?",
            (proposition_id,),
        ).fetchone()
    finally:
        con.close()
    if row is None:
        raise ValueError(f"Unknown proposition: {proposition_id}")
    if row["kind"] != "proposition":
        raise ValueError(
            f"triage_for_formalization expects a proposition; got kind={row['kind']!r}"
        )
    text = row["text"] or ""
    n = len(text)
    whitelist_hits = _keyword_hits(text, _WHITELIST)
    blacklist_hits = _keyword_hits(text, _BLACKLIST)

    reasons: list[str] = []
    eligible = True
    if n < 10:
        eligible = False
        reasons.append(f"text too short ({n} chars; need >= 10)")
    if n > 600:
        eligible = False
        reasons.append(f"text too long ({n} chars; need <= 600 for single-page proofs)")
    if not whitelist_hits:
        eligible = False
        reasons.append(
            "no mathlib-friendly keywords detected; expand the proposition or add "
            "a manual whitelist override"
        )
    else:
        reasons.append(f"whitelist keywords matched: {whitelist_hits}")
    if blacklist_hits:
        eligible = False
        reasons.append(
            f"blacklist keywords matched (mathlib coverage thin): {blacklist_hits}"
        )

    if not eligible:
        # Rejected: don't pretend to estimate effort. The agent treats this
        # as "do not attempt" regardless; downstream audits should distinguish
        # rejection from a hard-but-eligible attempt.
        difficulty = "n/a"
    elif n <= 250 and len(whitelist_hits) >= 2:
        difficulty = "low"
    else:
        difficulty = "med"

    return {
        "proposition_id": proposition_id,
        "eligible": eligible,
        "reasons": reasons,
        "estimated_difficulty": difficulty,
        "whitelist_hits": whitelist_hits,
        "blacklist_hits": blacklist_hits,
        "length": n,
    }


def record_lean_attempt(
    proposition_id: str,
    status: str,
    lean_source: str = "",
    stderr: str = "",
    duration_sec: float | None = None,
    triage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one Lean formalisation attempt.

    The agent calls this AFTER it has run lean-lsp-mcp's ``lean_verify``
    (or has decided to mark queued/running/timeout). Cross-trunk
    side-effects -- ``attach_evidence`` on success, ``record_failure``
    with ``domain='proof'`` on failure -- are deliberately **not**
    triggered here. The prover agent's prompt instructs it to make
    those follow-up calls explicitly so the action is auditable in the
    cockpit's event stream.
    """
    if status not in VALID_STATUS:
        raise ValueError(
            f"status must be in {sorted(VALID_STATUS)}; got {status!r}"
        )
    if duration_sec is not None and duration_sec < 0:
        raise ValueError("duration_sec must be non-negative")

    triage = triage or {}
    eligible_int = 1 if bool(triage.get("eligible")) else 0
    reasons_json = json.dumps(triage.get("reasons") or [])
    difficulty = triage.get("estimated_difficulty", "unknown")
    if difficulty not in VALID_DIFFICULTY:
        raise ValueError(
            f"triage.estimated_difficulty must be in {sorted(VALID_DIFFICULTY)}; got {difficulty!r}"
        )

    with tx() as con:
        prop = con.execute(
            "SELECT node_id, kind FROM mem_nodes WHERE node_id = ?",
            (proposition_id,),
        ).fetchone()
        if prop is None:
            raise ValueError(f"Unknown proposition: {proposition_id}")
        if prop["kind"] != "proposition":
            raise ValueError(
                f"record_lean_attempt expects a proposition; got kind={prop['kind']!r}"
            )
        cur = con.execute(
            """
            INSERT INTO prv_lean_attempts(
              proposition_id, status, lean_source, stderr, duration_sec,
              triage_eligible, triage_reasons, triage_difficulty
            )
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                proposition_id,
                status,
                lean_source or "",
                stderr or "",
                float(duration_sec) if duration_sec is not None else None,
                eligible_int,
                reasons_json,
                difficulty,
            ),
        )
        attempt_id = int(cur.lastrowid)
        kind = "lean_proof_succeeded" if status == "verified" else (
            "lean_proof_failed" if status in {"failed", "timeout"} else "lean_proof_recorded"
        )
        _emit_event(
            con,
            kind,
            {
                "attempt_id": attempt_id,
                "proposition_id": proposition_id,
                "status": status,
                "duration_sec": duration_sec,
            },
        )
    return {
        "attempt_id": attempt_id,
        "proposition_id": proposition_id,
        "status": status,
    }


def list_lean_attempts(
    proposition_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Browse Lean attempts filtered by proposition and/or status."""
    if status is not None and status not in VALID_STATUS:
        raise ValueError(
            f"status filter must be in {sorted(VALID_STATUS)}; got {status!r}"
        )
    con = _connect()
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if proposition_id is not None:
            clauses.append("proposition_id = ?")
            params.append(proposition_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = con.execute(
            f"""
            SELECT attempt_id, proposition_id, status, lean_source, stderr,
                   duration_sec, triage_eligible, triage_reasons,
                   triage_difficulty, created_at
            FROM prv_lean_attempts
            {where}
            ORDER BY attempt_id DESC
            """,
            tuple(params),
        ).fetchall()
    finally:
        con.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            triage_reasons = json.loads(row["triage_reasons"] or "[]")
        except json.JSONDecodeError:
            triage_reasons = []
        out.append(
            {
                "attempt_id": row["attempt_id"],
                "proposition_id": row["proposition_id"],
                "status": row["status"],
                "lean_source": row["lean_source"],
                "stderr": row["stderr"],
                "duration_sec": row["duration_sec"],
                "triage_eligible": bool(row["triage_eligible"]),
                "triage_reasons": triage_reasons,
                "triage_difficulty": row["triage_difficulty"],
                "created_at": row["created_at"],
            }
        )
    return out
