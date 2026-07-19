# Walkthrough: Debugging a Failure

> 中文版本: [debugging-a-failure.zh-CN.md](debugging-a-failure.zh-CN.md)
> A short, focused walkthrough of how to use the failure ledger and replay tools when something goes wrong. Read [`first-research-task.md`](first-research-task.md) first if you have not yet.

When an experiment fails or produces unexpected results, the project gives you three tools that, together, prevent you from solving the same problem twice: `match_signatures`, `record_failure`, and `replay_counterfactual`. This walkthrough shows when to use each.

## The principle

Every failure is an opportunity to write a single line of memory. Done consistently, this turns the project into a personal expert system that remembers your mistakes for you.

## Step 1: when something fails, search first

Before you start debugging, ask the failure ledger:

```
mcp__memory__match_signatures situation="cuda out of memory during ViT training" k=5
```

This returns the top 5 historical failures ranked by BM25 over `(trigger, symptom, root_cause, resolution)`. If a similar failure exists, **read its resolution before opening any debugger**. You will save hours.

If nothing matches, proceed to step 2.

## Step 2: minimal reproduction

Get the failure to reproduce in the smallest possible script. This is good engineering practice independent of the project, but the smaller the repro, the more reusable the eventual record_failure entry will be.

A useful heuristic: if the repro is more than 50 lines, keep cutting.

## Step 3: bisect

Standard bisection. The destructive bash guard will stop you from accidentally running `git reset --hard` mid-bisect, so feel free to use git aggressively.

When you find the offending commit:

- Identify the **trigger** (what action caused the failure)
- Identify the **symptom** (what the user / system observed)
- Identify the **root cause** (the underlying reason)
- Identify the **resolution** (what made it go away)

If you cannot articulate all four, keep digging.

## Step 4: record the failure

```
mcp__memory__record_failure \
  trigger="ViT training with batch_size=128 on 24GB GPU" \
  symptom="CUDA out of memory after first forward pass" \
  root_cause="ViT-B/16 activation memory ~2x larger than ResNet-50 at same batch size" \
  resolution="reduce batch_size to 64 or use gradient checkpointing"
```

The system computes a deterministic signature. If you (or someone else) record an identical failure later, `seen_count` increments instead of creating a duplicate row. The full-text search index updates automatically.

## Step 5: when the failure is conceptual, not mechanical

Sometimes the "failure" is a hypothesis being refuted by evidence, not a script crashing. In that case, the right tool is not `record_failure` but the graph itself:

```
mcp__memory__attach_evidence node_id=<hypothesis_id> evidence_text="..." polarity=refutes
mcp__memory__mark_refuted node_id=<hypothesis_id> reason="..." evidence_ids=[<the new evidence>]
```

This propagates through the BT layer (`update_bt_rating` with `source=metric_diff`) and the cockpit's tree pane shows the hypothesis as struck-through.

## Step 6: the counterfactual case

Suppose you pruned a hypothesis branch a week ago, and new evidence makes you wonder whether you pruned the right one. You want to ask "what if we had kept that branch?" without disturbing the current state.

This is the replay tool's job:

```
# First, list the snapshots you have
mcp__memory__list_replay_branches

# Then, create a counterfactual branch from a chosen snapshot
mcp__memory__replay_counterfactual \
  snapshot_id=snap_2026-04-21 \
  counterfactual="kept hyp_8a3f instead of hyp_2b1e"
```

This writes a row into `mem_replay_branches` and emits `replay_branch_created`. The main `mem_nodes` and `mem_bt_ratings` are not touched. You can now manually or automatically explore the counterfactual without risk.

When you are done with the replay, simply ignore it — replay branches do not feed back into the main graph unless you explicitly promote them via a new `propose_hypothesis`.

## Step 7: when the failure is a leakage finding

If `leakage_check` flagged your script and the hook denied a `Write`, that is by design. The right move is **not** to bypass the hook. Instead:

1. Read the finding's `message` field — it points to the exact line and rule
2. Refactor the script to fit the model on training data only, then transform test data with the fitted scaler
3. Re-run `leakage_check` on the new script
4. When clean, retry the `Write`

If you genuinely believe the leakage check is wrong (false positive), record it as a failure with `root_cause="leakage_check rule X false-positive on pattern Y"`. This builds the case for refining the rule later.

## Step 8: when the failure is a budget overflow

`budget_consume` returned `{"ok": False, "error": "budget_exceeded"}`. The budgeter agent should have caught this earlier; if it did not, the budgeter prompt may need updating.

In the moment, the right responses are:

- **Halt the current operation** and reassess the plan
- **Check `res_budget_ledger`** to see which axis blew the budget
- **Either negotiate a budget increase** with explicit user approval, or **drop the operation**

Do not silently raise the cap and continue. The budget is there to make over-spending visible.

## Step 9: closing the loop

Once the failure is fixed, also do:

```
mcp__memory__attach_evidence node_id=<original_hypothesis> \
  evidence_text="bug fixed in commit abc123, results now reproduce" \
  polarity=supports
```

This keeps the hypothesis graph honest about what we know now versus what we knew yesterday.

## Anti-patterns

- **Debugging without first calling `match_signatures`.** You may waste hours on a problem someone has already solved.
- **Not recording the failure once it is fixed.** The next person (which may be you in three months) will hit the same wall.
- **Recording vague failures.** `trigger="error"` and `symptom="it broke"` are useless. The four fields exist for a reason.
- **Mutating the main graph to "what-if" something.** That is what `replay_counterfactual` is for. The main graph should always reflect what actually happened.

## A closing note

Failure records can reduce the time needed to diagnose similar problems later.
Recording the symptoms, cause, and solution usually takes little time and can
prevent the same investigation from being repeated.
