---
name: writeup-sop
description: Writing reports or papers. Use when producing any .md file that makes claims about experimental results.
---

# Writeup SOP

HARD RULE: every numeric claim in a report must be traceable via `mcp__verify__check_provenance`. The PreToolUse hook may block unprovenanced claims on file write.

Workflow:
1. List every claim you want to make.
2. For each claim, call `mcp__verify__check_provenance`. Missing provenance means re-run or remove the claim.
3. If you mention hypothesis rankings from `$elo-select`, include the Elo score next to each discussed hypothesis and ground that number before writing it into markdown.
4. Write the report.
