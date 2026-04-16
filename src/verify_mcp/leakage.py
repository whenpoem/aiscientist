"""AST-based leakage checks."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class Finding:
    rule: str
    line: int
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


_HELDOUT_NEEDLES = ("held_out", ".research-agent", "heldout")
_READ_FUNCS = {"open", "read_csv", "read_parquet", "load", "loadtxt", "read_json"}
_CONCAT_FUNCS = {"concat", "concatenate", "vstack", "hstack", "column_stack"}


def _func_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _string_literals(node: ast.AST) -> Iterable[str]:
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            yield child.value


def scan_python(src: str) -> list[Finding]:
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [Finding("syntax", exc.lineno or 1, exc.msg)]

    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = _func_name(node.func)
        if func_name in _READ_FUNCS:
            for literal in _string_literals(node):
                lowered = literal.replace("\\", "/").lower()
                if any(needle in lowered for needle in _HELDOUT_NEEDLES):
                    findings.append(
                        Finding(
                            "heldout_access",
                            node.lineno,
                            "Possible held-out access detected; use verify-mcp instead of reading reserved data directly.",
                        )
                    )
                    break
        if func_name == "fit" and node.args:
            arg0 = node.args[0]
            concat_name = _func_name(arg0.func) if isinstance(arg0, ast.Call) else None
            if concat_name in _CONCAT_FUNCS:
                findings.append(
                    Finding(
                        "fit_on_concatenated",
                        node.lineno,
                        "Model/scaler appears to fit on concatenated data.",
                    )
                )
    return findings


def scan_file(path: str) -> list[Finding]:
    return scan_python(Path(path).read_text(encoding="utf-8"))

