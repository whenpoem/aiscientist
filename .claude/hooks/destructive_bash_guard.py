#!/usr/bin/env python
"""Block destructive shell commands unless explicitly confirmed."""

from __future__ import annotations

import json
import re
import sys

PATTERNS = [
    re.compile(r"\brm\s+-rf\b", re.IGNORECASE),
    re.compile(r"\bRemove-Item\b.*\b-Recurse\b", re.IGNORECASE),
    re.compile(r"\bgit\s+push\b.*--force", re.IGNORECASE),
    re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE),
    re.compile(r"\bgit\s+clean\s+-f(?:d|x|dx|fdx)*\b", re.IGNORECASE),
    re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bDROP\s+DATABASE\b", re.IGNORECASE),
    re.compile(r"\bdel\s+/s\b", re.IGNORECASE),
    re.compile(r"\bformat\s+[A-Za-z]:", re.IGNORECASE),
]


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    command = ""
    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, dict):
        command = str(tool_input.get("command", ""))
    if "# CONFIRM_DESTRUCTIVE" in command:
        print("{}")
        return
    if any(pattern.search(command) for pattern in PATTERNS):
        print(
            json.dumps(
                {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "Destructive bash command blocked. Append # CONFIRM_DESTRUCTIVE to proceed.",
                }
            )
        )
        raise SystemExit(2)
    print("{}")


if __name__ == "__main__":
    main()

