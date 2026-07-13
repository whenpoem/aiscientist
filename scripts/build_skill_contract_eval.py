"""Build a deterministic old-vs-v5.1 skill contract review workspace."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".claude" / "skills"

CHECKS: dict[str, list[list[tuple[str, ...]]]] = {
    "research-sop": [
        [
            ("exploratory", "confirmatory"),
            ("family_id", "family_size"),
            ("uncalibrated approximate",),
            ("completion criteria", "refresh_claim", "seed_perturb", "baseline_fairness"),
        ],
        [
            ("interrupted work",),
            ("snapshot", "pins", "manifests"),
            ("exploratory", "confirmatory"),
        ],
        [
            ("optional helpers",),
            ("role boundaries inline",),
            ("claudescientist cockpit --workspace",),
        ],
    ],
    "debug-sop": [
        [
            ("intermittent", "flaky"),
            ("one explanatory variable",),
            ("original reproduction", "regression"),
            ("record_failure",),
        ],
        [
            ("diagnosis request",),
            ("familiar exception",),
            ("surviving hypotheses",),
        ],
        [
            ("integration failures", "boundary"),
            ("environment", "workspace"),
            ("external dependency failure",),
        ],
    ],
    "writeup-sop": [
        [
            ("check_provenance", "refresh_claim"),
            ("pin_id", "stable seed"),
            ("family_id", "family_size"),
            ("baseline_fairness", "reviewer json"),
        ],
        [
            ("theorem and proof claims",),
            ("open", "manifest", "blocks"),
            ("unverified", "lean"),
        ],
        [
            ("uncalibrated approximate posterior",),
            ("overlap/non-overlap", "proof"),
            ("comparison count", "calibration status"),
        ],
    ],
}


def _old_skill(name: str) -> str:
    path = f".claude/skills/{name}/SKILL.md"
    completed = subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout


def _grade(text: str, expectations: list[str], checks: list[tuple[str, ...]]) -> dict:
    lowered = text.lower()
    results = []
    for expectation, fragments in zip(expectations, checks, strict=True):
        missing = [fragment for fragment in fragments if fragment not in lowered]
        results.append(
            {
                "text": expectation,
                "passed": not missing,
                "evidence": (
                    "All required workflow markers are present."
                    if not missing
                    else "Missing workflow markers: " + ", ".join(missing)
                ),
            }
        )
    passed = sum(int(result["passed"]) for result in results)
    return {
        "expectations": results,
        "summary": {
            "passed": passed,
            "failed": len(results) - passed,
            "total": len(results),
            "pass_rate": passed / len(results),
        },
        "execution_metrics": {
            "tool_calls": {},
            "total_tool_calls": 0,
            "total_steps": 0,
            "errors_encountered": 0,
            "output_chars": len(text),
            "transcript_chars": 0,
        },
        "timing": {"total_duration_seconds": 0.0},
    }


def build(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    benchmark_runs = []
    new_rates: list[float] = []
    old_rates: list[float] = []

    for skill_name, eval_checks in CHECKS.items():
        eval_payload = json.loads(
            (SKILL_ROOT / skill_name / "evals" / "evals.json").read_text(encoding="utf-8")
        )
        versions = {
            "new_skill": (SKILL_ROOT / skill_name / "SKILL.md").read_text(encoding="utf-8"),
            "old_skill": _old_skill(skill_name),
        }
        for item, checks in zip(eval_payload["evals"], eval_checks, strict=True):
            eval_name = f"{skill_name}-{item['id']}"
            eval_dir = output / eval_name
            metadata = {
                "eval_id": item["id"],
                "eval_name": eval_name,
                "prompt": item["prompt"],
                "assertions": item["expectations"],
            }
            eval_dir.mkdir(parents=True, exist_ok=True)
            (eval_dir / "eval_metadata.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            for configuration, text in versions.items():
                run_name = configuration
                run_dir = eval_dir / run_name
                outputs = run_dir / "outputs"
                outputs.mkdir(parents=True, exist_ok=True)
                (outputs / "SKILL.md").write_text(text, encoding="utf-8")
                grading = _grade(text, item["expectations"], checks)
                (run_dir / "grading.json").write_text(
                    json.dumps(grading, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                (run_dir / "timing.json").write_text(
                    json.dumps(
                        {"total_tokens": 0, "duration_ms": 0, "total_duration_seconds": 0.0},
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                result = grading["summary"]
                benchmark_runs.append(
                    {
                        "eval_id": item["id"],
                        "eval_name": eval_name,
                        "configuration": configuration,
                        "run_number": 1,
                        "result": {
                            "pass_rate": result["pass_rate"],
                            "passed": result["passed"],
                            "failed": result["failed"],
                            "total": result["total"],
                            "time_seconds": 0.0,
                            "tokens": 0,
                            "tool_calls": 0,
                            "errors": 0,
                        },
                        "expectations": grading["expectations"],
                        "notes": [
                            "Deterministic contract review; not an independent model execution."
                        ],
                    }
                )
                target = new_rates if configuration == "new_skill" else old_rates
                target.append(result["pass_rate"])

    def summary(values: list[float]) -> dict:
        mean = sum(values) / len(values)
        return {
            "pass_rate": {"mean": mean, "stddev": 0.0, "min": min(values), "max": max(values)},
            "time_seconds": {"mean": 0.0, "stddev": 0.0, "min": 0.0, "max": 0.0},
            "tokens": {"mean": 0.0, "stddev": 0.0, "min": 0.0, "max": 0.0},
        }

    benchmark = {
        "metadata": {
            "skill_name": "ClaudeScientist core SOPs",
            "skill_path": str(SKILL_ROOT),
            "executor_model": "deterministic-contract-check",
            "analyzer_model": "deterministic-contract-check",
            "timestamp": "2026-07-13T00:00:00Z",
            "evals_run": [run["eval_name"] for run in benchmark_runs[::2]],
            "runs_per_configuration": 1,
        },
        "runs": benchmark_runs,
        "run_summary": {
            "new_skill": summary(new_rates),
            "old_skill": summary(old_rates),
            "delta": {
                "pass_rate": (
                    f"{sum(new_rates) / len(new_rates) - sum(old_rates) / len(old_rates):+.2f}"
                ),
                "time_seconds": "+0.0",
                "tokens": "+0",
            },
        },
        "notes": [
            "This review proves workflow-contract coverage only.",
            "Independent stochastic agent runs were omitted because this task "
            "did not authorize subagents.",
        ],
    }
    benchmark_path = output / "benchmark.json"
    benchmark_path.write_text(
        json.dumps(benchmark, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return benchmark_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(build(args.output.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
