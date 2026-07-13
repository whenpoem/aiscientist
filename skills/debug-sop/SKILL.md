---
name: debug-sop
description: Diagnose errors, failed tests, crashes, hangs, regressions, suspicious outputs, and unexpected experimental results through reproducible hypothesis-driven debugging. Use whenever a script or system behaves incorrectly, even if the user only says it is broken or pastes an error. Respect diagnosis-only requests; implement a fix only when authorized.
---

# Debug SOP

## Inputs and output

Capture the exact symptom, expected behavior, reproduction command, relevant
inputs, environment, first known bad state, and whether fixing is authorized.
Return a compact incident report with reproduction, root cause or surviving
hypotheses, evidence, changed files if any, verification commands, and the
failure-ledger id.

## 1. Recover history before guessing

1. Call `mcp__memory__match_signatures` with the exact error plus the operation
   that triggered it. Read matching resolutions, but verify they still apply.
2. Inspect recent relevant changes, logs, configuration, and run manifests.
3. Distinguish the visible symptom from a proposed cause. Do not edit merely
   because a familiar exception suggests an easy fix.

## 2. Reproduce and bound the failure

1. Run the smallest safe command that should reproduce the symptom.
2. Record whether it is deterministic, intermittent, machine-specific,
   data-specific, or dependent on ordering/timing.
3. If reproduction would be destructive, costly, or use reserved data, stop
   and request the needed authority or choose a non-mutating probe.
4. If the failure cannot be reproduced, compare environment, command, inputs,
   Git state, and dependency locks before declaring it gone.

## 3. Build and eliminate hypotheses

List plausible causes and, for each, the cheapest observation that would
distinguish it. Prefer direct evidence in this order:

1. exact traceback, exit code, or incorrect output;
2. minimal reproduction;
3. focused logging or state inspection;
4. controlled input/config variation;
5. history or non-destructive bisection.

Change one explanatory variable at a time. Do not use destructive Git reset or
discard unrelated user work during bisection.

## 4. Isolate the root cause

Reduce the case until removing one condition removes the failure. For data or
statistical failures, also check leakage, seed sensitivity, stale code/config,
and baseline-budget mismatch. For integration failures, verify each boundary
separately: executable discovery, configuration loading, process startup,
protocol exchange, shared workspace/state path, then UI behavior.

If multiple causes remain possible, say which evidence is missing instead of
choosing the most convenient story.

## 5. Fix only when authorized

For a diagnosis request, stop after proving the cause and proposing a scoped
fix. For a requested repair:

1. make the smallest change that removes the cause;
2. preserve compatibility and unrelated user changes;
3. add or update a regression test that failed before the fix;
4. avoid hiding the symptom with broad exception handling or relaxed checks.

## 6. Verify proportionally

Run the minimal reproduction first, then the focused regression tests, then
the repository-required broader checks. Verify the original user-visible path,
not only the helper function. For intermittent failures, repeat enough times to
make the remaining uncertainty explicit.

## 7. Record the failure

Call `mcp__memory__record_failure` with:

- `trigger`: operation and preconditions;
- `symptom`: exact externally visible failure;
- `root_cause`: proven mechanism, not a guess;
- `resolution`: change and verification command;
- appropriate empirical or proof domain.

If unresolved, record the diagnostic evidence and surviving hypotheses rather
than inventing a root cause.

## Recovery branches

- Cannot reproduce: compare manifests and ask for the missing command/input.
- Flaky: identify timing, ordering, shared-state, or randomness dimensions and
  run controlled repetitions.
- External dependency failure: prove the local boundary is healthy, record the
  upstream error, and provide a safe retry or fallback.
- Fix causes a different regression: revert only your scoped change, preserve
  evidence, and return to the hypothesis list.
- Repeated dead end: stop changing code, summarize tested hypotheses, and state
  the exact user input or external change needed.

## Completion criteria

Debugging is complete when the symptom is reproducible or its absence is
explained, the root cause is supported by discriminating evidence, any
authorized fix passes the original reproduction and regression checks, and the
failure ledger contains enough detail for the next agent to avoid repeating
the investigation.
