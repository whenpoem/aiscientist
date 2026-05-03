# Plan: ClaudeScientist V3.0 — From bookkeeping to active inference

> **Status**: shipped. All 5 phases complete; 108/108 tests green; ruff clean.
> **Theme**: research pipeline as a continuously-running, budgeted Bradley-Terry tournament with honest confidence intervals.
> **Vehicle**: Windows 11, project at `D:\aiscientist\claudescientist`, `uv` + Python 3.11, single-file SQLite at `.research-agent/state.db`.
> **Locked decisions for V3.0**:
> - Auto-prune is **dry-run by default**; users opt-in with `RESEARCH_AGENT_AUTO_PRUNE=1`.
> - BT layer adds new tables; legacy `mem_nodes.elo_score` stays as a read-only compatibility column. `record_judgement` dual-writes.
> - All new MCP tools land in the existing `memory` and `verify` servers; no new MCP server.

---

## 1. Why V3.0

After v0.2 stabilised, two real-world friction points emerged:

1. **Elo K=32 single-shot ranking signal is weak.** [src/memory_mcp/impl.py:364-430](../src/memory_mcp/impl.py) updates `mem_nodes.elo_score` once per `record_judgement` with no joint estimation, no confidence interval, and no engineered way to "pause low-scoring directions". The user's [创新点.md:1-2](../创新点.md) spelled out the missing pieces: (a) Elo → Bradley-Terry, (b) score continuously through the experiment and pause low-scoring branches.
2. **Numbers are not yet trustworthy.** `ver_seed_runs.verdict` decides whether a metric pin is stable, but there is no preregistration, and no provenance staleness detection. Realtime pruning on top of stale metrics + uncorrected multiple comparisons would amplify false positives.

V3.0 closes both gaps and adds the audit / reproducibility layer needed to make automatic pruning safe.

---

## 2. Architecture delta

```
┌──────────────────────────────────────────────────────────────────────┐
│  memory_mcp tools                                                    │
│    propose_hypothesis    -> seeds mem_bt_ratings row                 │
│    record_judgement      -> dual-writes mem_judgements + BT          │
│    update_bt_rating      -> NEW: incremental Laplace-Bayes BT update │
│    get_bt_leaderboard    -> NEW: strength + 95% LUCB interval        │
│    suggest_pause_low_strength -> NEW: dry-run by default             │
│    resume_branch         -> NEW: reverse a paused branch             │
│    expected_information_gain -> NEW: pick the next experiment        │
│    record_calibration / calibration_report -> NEW: reliability       │
│    replay_counterfactual / list_replay_branches -> NEW: what-if      │
│                                                                      │
│  verify_mcp tools                                                    │
│    record_provenance     -> now optionally hashes input_files        │
│    refresh_claim         -> NEW: re-hash inputs, mark stale rows     │
│    preregister / resolve_preregistration -> NEW with BH/Bonferroni   │
│    list_preregistrations -> NEW                                      │
│    budget_check / budget_consume -> NEW: res_budget_ledger gate      │
│                                                                      │
│  agents:        + reviewer.md, + budgeter.md                         │
│  skills:        + bt-tournament/, + preregister/, + replay/          │
│                 (elo-select stays as deprecated shim)                │
│  research-sop:  references bt-tournament + preregister + replay      │
└──────────────────────────────────────────────────────────────────────┘
```

The hook chain (PreToolUse / PostToolUse / UserPromptSubmit / Stop) is unchanged — V3.0 only adds new SQL tables and MCP tools that the existing hooks can read.

---

## 3. SQLite schema delta

Memory schema bumped to version 4, verify to version 4. All migrations are `CREATE TABLE IF NOT EXISTS` so v0.2 databases upgrade in place without backfill.

| New table | Purpose | Component |
|---|---|---|
| `mem_bt_ratings` | per-node BT strength, variance, comparison count, status | memory |
| `mem_bt_comparisons` | append-only ledger of pairwise comparisons | memory |
| `meta_calibration` | reliability-diagram buckets per agent | memory |
| `mem_replay_branches` | counterfactual what-if branches | memory |
| `ver_provenance_dag` | input-hash chain for `refresh_claim` | verify |
| `ver_preregistrations` | locked falsification targets | verify |
| `res_budget_ledger` | wallclock / token / heldout-query budget | verify |

Cockpit event kinds added (each must include `node_id`, `hypothesis_id`, or both in the payload):
`bt_rating_updated`, `branch_pause_suggested`, `branch_paused`, `branch_promoted`,
`prereg_locked`, `prereg_resolved`, `prov_dag_stale`, `replay_branch_created`,
`budget_exceeded`.

---

## 4. Bradley-Terry math

Online update via Laplace approximation for one comparison `winner=i`, `loser=j`:

```
diff   = clip(theta_i - theta_j, [-30, 30])
p      = sigmoid(diff)
fisher = max(1e-6, p * (1-p)) * weight
delta  = lr * weight * (1 - p)            # lr = 0.5
theta_i := clip(theta_i + delta, [-12, 12])
theta_j := clip(theta_j - delta, [-12, 12])
var_i := 1 / (1/var_i + fisher)
var_j := 1 / (1/var_j + fisher)
```

Confidence interval on the leaderboard: `lcb = strength - 1.96 * sqrt(var)`, `ucb = strength + 1.96 * sqrt(var)`. Beta(1,1) shrinkage comes from the initial `strength_var = 1.0` plus the strength clip; deterministic blowups (a node always wins) are bounded.

`suggest_pause_low_strength(ucb_threshold, min_comparisons=6)` flags any active hypothesis with `n_comparisons >= min_comparisons` and `ucb < ucb_threshold`. By default it only emits `branch_pause_suggested`. With `RESEARCH_AGENT_AUTO_PRUNE=1` it additionally flips `mem_bt_ratings.status` to `paused` and emits `branch_paused`. `resume_branch` reverses either.

---

## 5. Test inventory (added in V3.0)

| Test file | Coverage |
|---|---|
| `tests/memory_mcp/test_bt_rating.py` | seeding, MM update, clip, dual-write, leaderboard ordering |
| `tests/memory_mcp/test_pruning.py` | dry-run, env-flag pause, min_comparisons guard, resume, EIG |
| `tests/memory_mcp/test_calibration.py` | bucketing, Brier score, drift |
| `tests/memory_mcp/test_replay.py` | non-mutation, ordering, validation |
| `tests/verify_mcp/test_prov_dag.py` | record path, stale detection, missing claims |
| `tests/verify_mcp/test_preregister.py` | lock + resolve, BH correction tightens, double-resolve |
| `tests/verify_mcp/test_budget.py` | overflow blocks, check consistency |
| `tests/e2e/test_bt_smoke.py` | round-robin tournament leaderboard ordering |
| `tests/e2e/test_prereg_flow.py` | propose → preregister → seed_perturb → resolve |
| `tests/e2e/test_realtime_prune.py` | dry-run vs auto, resume |

Existing v0.2 tests remain untouched except [tests/e2e/test_smoke.py:65-87](../tests/e2e/test_smoke.py) which now asserts the SOP references `bt-tournament` + `preregister` (with `elo-select` retained as a deprecated shim).

Final regression: **108 passed, 0 failed, 0 skipped**, ruff clean.

---

## 6. Operator notes

```powershell
# Run V3.0 with realtime pruning enabled:
$env:RESEARCH_AGENT_AUTO_PRUNE = "1"
uv run python -m cockpit.tui

# In another terminal, the BT leaderboard updates as record_judgement runs:
uv run python -c "from memory_mcp.impl import get_bt_leaderboard; import json; print(json.dumps(get_bt_leaderboard(top_k=5), indent=2))"
```

The BT column is rendered inline in the cockpit's hypothesis tree pane: every hypothesis row now ends with `bt +0.42±0.13 n=7` (or `bt n/a` if no comparisons yet) followed by the legacy Elo number for visual continuity. Paused hypotheses get a `[paused]` amber badge.

---

## 7. Backwards compatibility

- v0.2 databases upgrade in place. All new tables are `IF NOT EXISTS` and the bootstrap functions backfill `mem_bt_ratings` rows for every existing hypothesis node.
- `mem_nodes.elo_score` is **kept** and **still updated** by `record_judgement` so any v0.2 reader still works. The new BT data lives on the new tables.
- `elo-select` skill is preserved as a deprecated shim with a banner directing users to `bt-tournament`. Existing prompts that reference `$elo-select` keep working.
- Auto-pruning is opt-in. Users who do nothing see only `branch_pause_suggested` events in the cockpit and `mem_bt_ratings.status` stays `active`.

---

## 8. References

- [创新点.md](../创新点.md) — original user-stated wishes
- [README.md](../README.md), [AGENTS.md](../AGENTS.md), [docs/design-contracts.md](design-contracts.md)
- BT MM algorithm: Hunter (2004), "MM Algorithms for Generalized Bradley-Terry Models"
- LUCB / best-arm identification: Kalyanakrishnan et al. (2012)
- Benjamini-Hochberg correction: classical FDR control
