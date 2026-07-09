# Walkthrough: Your First Research Task

> 中文版本: [first-research-task.zh-CN.md](first-research-task.zh-CN.md)
> A complete, end-to-end walkthrough of one research task running through ClaudeScientist. Read [`../overview.md`](../overview.md) first if you have not yet.

This walkthrough assumes you already have `uv sync` complete and the repository configured. We will run a small but realistic task: investigating whether per-head dropout helps Vision Transformer scaling. The exact subject does not matter — what matters is the shape of the workflow.

## 0. Prepare two terminals

Open two terminals from the repository root.

```powershell
# Terminal A: the AI client you selected (from the repo root)
claude
# Or, if setup selected codex/both:
codex -C .

# Terminal B: the cockpit TUI (from the repo root)
uv run python -m cockpit.tui
```

You should now see the empty hypothesis tree on the right. Everything below happens in Terminal A unless noted.

## 1. Kick off the research SOP

If Terminal A is Claude Code, type:

```
/research-sop investigate whether per-head dropout helps ViT scaling
```

If Terminal A is Codex, type:

```
$research-sop investigate whether per-head dropout helps ViT scaling
```

This starts `research-sop`, which runs the research steps. In Codex, you can also choose it from `/skills`. `/research-sop` is for Claude Code and usually fails in Codex. Within a few seconds you should see, in Terminal B:

- The cockpit's question node appears at the root of the tree
- Three to five hypothesis nodes spawn under it
- The event stream fills with `graph_delta` lines

What just happened under the hood:

1. Claude looked up `match_signatures("per-head dropout ViT scaling")` in the failure ledger
2. Claude called `query_literature(...)` to see whether prior papers were already ingested
3. (If literature was sparse) Claude spawned the `librarian` subagent, which fetched papers via `arxiv` and `openalex`, then called `ingest_paper` for each
4. Claude spawned the `researcher` subagent, which produced the candidate hypotheses and called `propose_hypothesis` for each

## 2. Run a Bradley-Terry tournament

The `bt-tournament` skill should fire automatically because there are at least three hypotheses. If it does not, type:

```
/bt-tournament
```

For each pair of hypotheses, Claude will:

1. Call `judge_hypotheses(a_id, b_id)` to fetch the canonical comparison prompt
2. Decide a winner inline (Claude reads the prompt, applies the criteria, picks)
3. Call `record_judgement(a_id, b_id, winner_id, reason)`

In Terminal B, each comparison emits a `bt_rating_updated` event. The hypothesis tree's trailing column updates from `bt n/a` to `bt +0.42 ±0.13 n=3` style readouts.

When the tournament finishes, ask for the leaderboard:

```
mcp__memory__get_bt_leaderboard top_k=5
```

You will see something like:

```
1. hyp_8a3f...   strength=+1.84   lcb=+0.97  ucb=+2.71   n=4
2. hyp_2b1e...   strength=+0.31   lcb=-0.55  ucb=+1.18   n=3
3. hyp_c92d...   strength=-0.62   lcb=-1.48  ucb=+0.25   n=3
...
```

The top hypothesis with non-overlapping intervals against the runner-up is the candidate to move forward.

## 3. Preregister confirmatory experiments

If the next run is meant to support a main confirmatory claim, lock the target before running it. If you are still exploring, label the run exploratory and do not present it as a final claim.

```
/preregister hyp_8a3f... metric=test_accuracy direction=higher_better threshold=0.85
```

The `preregister` tool writes a `ver_preregistrations` row with `status='open'` and emits a `prereg_locked` event. The cockpit's "Claims" tab now shows a pending entry.

## 4. Implement the experiment

Hand off to the engineer subagent:

```
@engineer implement the dropout intervention as a small MNIST-proxy training script with --seed argument
```

The engineer will write the script. Several hooks fire automatically as it does:

- **Before the `Write`**: `leakage_guard.py` scans the file for known leakage patterns. If the engineer accidentally writes `model.fit(pd.concat([train, test]))`, the write is blocked outright.
- **Before any `Bash`**: `destructive_bash_guard.py` checks for things like `rm -rf`. They are blocked unless the command ends with `# CONFIRM_DESTRUCTIVE`.

The engineer will then run the script. As it runs:

- `provenance_log.py` (PostToolUse) extracts every `accuracy: 0.91` style number from stdout and inserts it into `ver_provenance`

## 5. Verify with multiple seeds

Run the seed-perturbation check:

```
mcp__verify__seed_perturb script_path=mnist_proxy.py seeds=[0,1,2]
```

This reruns the script three times with different `--seed` values, computes the mean and standard deviation of the test accuracy, and writes to `ver_seed_runs`. The default stability check uses an automatic tolerance that behaves like an absolute threshold for small bounded metrics and a relative threshold for larger-scale metrics. The cockpit's "Claims" tab now shows ✓ or ✗ next to the metric.

## 6. Pin the metric and resolve the preregistration

Pin the result:

```
mcp__verify__pin_metric claim="vit_dropout_test_accuracy" value=0.873 session_id=<auto> source_command="uv run python mnist_proxy.py --seed 0"
```

This creates a `ver_metric_pins` row linked to the seed run. Now resolve the preregistration:

```
mcp__verify__resolve_preregistration prereg_id=preg_... observed_value=0.873
```

If the observed value beats the threshold in the locked direction, status flips to `met`. If you also passed an `observed_p_value`, the configured multiple-comparison correction is applied across all currently-open preregistrations. New prereg rows use `bonferroni`; old `bh` rows remain accepted as a compatibility alias for the same Bonferroni-style calculation.

## 7. Spot-check the provenance DAG

If the experiment depends on input data files, refresh the claim:

```
mcp__verify__refresh_claim claim="vit_dropout_test_accuracy"
```

This re-hashes every input file in the claim's DAG. If any file drifted since the original `record_provenance`, the claim is marked `stale` and a `prov_dag_stale` event fires. Stale provenance blocks publication-critical claims; missing DAG entries are surfaced as unchecked audit context.

## 8. Summarize and pause weak branches

Look at the leaderboard one more time:

```
mcp__memory__get_bt_leaderboard
```

Identify hypotheses whose UCB is well below zero. Suggest pausing them:

```
mcp__memory__suggest_pause_low_strength ucb_threshold=-0.5
```

By default this **only emits suggestions** — it does not actually pause anything. If you have set `RESEARCH_AGENT_AUTO_PRUNE=1`, the suggested branches are paused immediately. Either way, you can reverse with `resume_branch(node_id, reason)`.

## 9. Hand off to writeup

Now you can ask Claude to draft a short writeup:

```
@reviewer prepare a one-page summary of the dropout investigation
```

The reviewer agent enforces the writeup contract for publication-critical claims: central confirmatory metrics need a metric pin, stable seed verdict, met preregistration, and non-stale provenance. Exploratory claims and context numbers must be labelled honestly rather than forced through every gate.

## 10. End the session

Quit Claude Code in Terminal A, then quit the TUI in Terminal B (press `q`). Restart both. You should see the entire graph, all BT ratings, all preregistrations, and all metric pins persist exactly as you left them — the SQLite file is the only state.

## What you have just done

- Generated and persisted a hypothesis graph
- Ranked candidates with a Bradley-Terry tournament
- Locked a falsification target before running confirmatory code
- Implemented an experiment with leakage and destructive-command guards
- Verified the result across three random seeds
- Recorded provenance with file fingerprints
- Resolved the preregistration with multiple-comparison correction
- Pruned weak branches in dry-run
- Drafted a writeup that enforces all of the above

This is the full v3.0 loop. Other workflows ([writing a paper](writing-a-paper.md), [debugging a failure](debugging-a-failure.md)) cover narrower slices of the same machinery.

## Common surprises

- **The cockpit lags by up to one second** — that is the polling interval, not a bug.
- **Pressing `n` in the cockpit does not interrupt the current tool call** — interventions are queued and delivered at the next `UserPromptSubmit` or `Stop` event. This is intentional.
- **The first run creates `.research-agent/state.db`** — you can delete the directory to start fresh, but it will erase all memory.
- **MCP servers must be restarted to pick up code changes** — Claude Code spawns them at session start and holds them. Restart Claude Code to reload.
