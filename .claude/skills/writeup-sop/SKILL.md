---
name: writeup-sop
description: Writing reports or papers. Use when producing any .md file that makes claims about experimental results.
---

# Writeup SOP

HARD RULE: every publication-critical result metric or statistical claim in a report must be traceable via `mcp__verify__check_provenance`. Context numbers (dates, versions, seed counts, baseline counts, model sizes, timeouts) should be accurate, but they are not provenance gates by themselves. The PreToolUse hook may block obvious unprovenanced labelled metrics on file write.

Workflow:
1. List every result claim you want to make and classify it as confirmatory, exploratory, or context.
2. For each publication-critical metric or statistical claim, call `mcp__verify__check_provenance`. Missing provenance means re-run, downgrade the claim to exploratory/context, or remove it.
3. If you mention hypothesis rankings from `$bt-tournament`, include the BT strength / interval only when it is part of the argument. Do not turn every rank, seed count, or version number into a hard provenance gate.
4. Write the report.
