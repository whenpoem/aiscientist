---
name: debug-sop
description: Systematic debugging. Use when a script errors or produces unexpected results.
---

# Debug SOP

1. Call `mcp__memory__match_signatures` with the error message. If a similar past failure exists, use that resolution first.
2. If there is no match, make a minimal reproduction and bisect.
3. When resolved, always call `mcp__memory__record_failure` with trigger, symptom, cause, and resolution.
