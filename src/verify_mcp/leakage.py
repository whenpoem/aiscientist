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
_FIT_FUNCS = {"fit", "fit_transform", "partial_fit"}
_SPLIT_FUNCS = {"train_test_split"}
_TRANSFORM_FUNCS = {"fit_transform", "scale", "minmax_scale", "robust_scale", "normalize"}
_EVAL_NEEDLES = ("test", "val", "valid", "eval", "dev", "heldout", "holdout")


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


def _base_name(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _base_name(node.value)
    if isinstance(node, ast.Subscript):
        return _base_name(node.value)
    return None


def _looks_like_eval_split(name: str | None) -> bool:
    if not name:
        return False
    lowered = name.lower()
    return any(needle in lowered for needle in _EVAL_NEEDLES)


def scan_python(src: str) -> list[Finding]:
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [Finding("syntax", exc.lineno or 1, exc.msg)]

    findings: list[Finding] = []
    transformed_vars: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Call):
                func_name = _func_name(node.value.func)
                if func_name in _TRANSFORM_FUNCS and node.value.args:
                    transformed_vars[target.id] = node.lineno

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
                            "Possible held-out access detected; "
                            "use verify-mcp instead of reading reserved data directly.",
                        )
                    )
                    break

        if func_name in _SPLIT_FUNCS:
            for arg in node.args:
                arg_name = _base_name(arg)
                if arg_name in transformed_vars:
                    findings.append(
                        Finding(
                            "split_after_global_transform",
                            node.lineno,
                            "train_test_split() appears to run after "
                            "a fit/transform on the full dataset.",
                        )
                    )
                    break

        if func_name not in _FIT_FUNCS:
            continue

        if node.args:
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

            if _looks_like_eval_split(_base_name(arg0)):
                findings.append(
                    Finding(
                        "fit_on_eval_split",
                        node.lineno,
                        "fit()/fit_transform() appears to run on test/validation data.",
                    )
                )

        if len(node.args) >= 2:
            feature_arg = node.args[0]
            target_arg = node.args[1]
            feature_base = _base_name(feature_arg)
            target_base = _base_name(target_arg)
            if isinstance(feature_arg, ast.Name) and feature_base and feature_base == target_base:
                findings.append(
                    Finding(
                        "target_in_features",
                        node.lineno,
                        "Features and target appear to come from the same full table "
                        "without dropping the label column first.",
                    )
                )
    return findings


def scan_file(path: str) -> list[Finding]:
    return scan_python(Path(path).read_text(encoding="utf-8"))
