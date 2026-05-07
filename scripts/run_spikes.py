#!/usr/bin/env python
"""One-shot post-install validator for the five Lean spike lemmas.

Walks the user-bootstrapped lake project at
``.research-agent/lean/claudescientist-proofs`` and runs ``lake build`` on
each spike file. Records the outcome (verified / failed / timeout) into
``prv_lean_attempts`` via ``prove_mcp.tools.lean_bridge.record_lean_attempt``
so the audit trail starts populated.

This script does **not** install Lean. It expects elan + lake on PATH and
the lakefile bootstrapped per ``docs/setup-lean.md``. If those are missing
it prints a clear instruction and exits with code 2.

Usage::

    uv run python scripts/run_spikes.py
    uv run python scripts/run_spikes.py --project-dir custom/path
    uv run python scripts/run_spikes.py --timeout 1800   # per spike, seconds
"""

from __future__ import annotations

import argparse
import shutil
import subprocess  # noqa: S404 -- we run lake build with a fixed argv list, no shell.
import sys
import time
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT = REPO_ROOT / ".research-agent" / "lean" / "claudescientist-proofs"
SPIKE_TEMPLATE_DIR = REPO_ROOT / ".research-agent" / "lean" / "spikes-template"
DEFAULT_TIMEOUT_SEC = 1800  # 30 min per spike


SPIKE_FILES = (
    "SampleMeanUnbiased.lean",
    "MarkovInequality.lean",
    "ChebyshevInequality.lean",
    "CauchySchwarz.lean",
    "BonferroniUnion.lean",
)


def _check_prereqs(project_dir: Path) -> str | None:
    """Return a human-readable error string if a prerequisite is missing,
    or None if everything looks ready."""
    if shutil.which("lake") is None:
        return (
            "lake not found on PATH. Install elan (lean version manager) "
            "first; see docs/setup-lean.md section 1."
        )
    if not project_dir.exists():
        return (
            f"lake project not found at {project_dir}. Run "
            "`lake new claudescientist-proofs math` per "
            "docs/setup-lean.md section 3."
        )
    lakefile = project_dir / "lakefile.lean"
    lakefile_toml = project_dir / "lakefile.toml"
    if not (lakefile.exists() or lakefile_toml.exists()):
        return f"no lakefile in {project_dir}; bootstrap not complete."
    return None


def _ensure_spikes_copied(project_dir: Path) -> Path:
    """Copy the spike templates into ClaudescientistProofs/Spikes/ if missing.
    Returns the directory containing the copied .lean files."""
    target_dir = project_dir / "ClaudescientistProofs" / "Spikes"
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in SPIKE_FILES:
        src = SPIKE_TEMPLATE_DIR / name
        dst = target_dir / name
        if not dst.exists() and src.exists():
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return target_dir


def _run_lake_build(project_dir: Path, target: str, timeout: int) -> tuple[str, str, float]:
    """Run `lake build <target>` and return (status, stderr, duration_sec).

    status ∈ {'verified', 'failed', 'timeout'}.
    """
    start = time.monotonic()
    try:
        result = subprocess.run(  # noqa: S603 -- argv is a fixed list, no shell.
            ["lake", "build", target],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "timeout", f"timed out after {timeout}s", float(timeout)
    duration = time.monotonic() - start
    if result.returncode == 0:
        return "verified", result.stderr or "", duration
    return "failed", result.stderr or result.stdout or "", duration


def run(
    project_dir: Path | None = None,
    *,
    timeout: int = DEFAULT_TIMEOUT_SEC,
    only: Iterable[str] | None = None,
    out=sys.stdout,
) -> dict[str, int]:
    """Programmatic entry point. Returns aggregate counts."""
    project = Path(project_dir) if project_dir else DEFAULT_PROJECT
    err = _check_prereqs(project)
    if err is not None:
        out.write(f"prereq error: {err}\n")
        return {"verified": 0, "failed": 0, "timeout": 0, "skipped": len(SPIKE_FILES)}

    _ensure_spikes_copied(project)
    selected = list(only) if only else list(SPIKE_FILES)

    # Lazy import so --help works without prove_mcp imports.
    from prove_mcp.tools.lean_bridge import record_lean_attempt

    verified = failed = timed_out = 0
    for fname in selected:
        spike_target = f"ClaudescientistProofs.Spikes.{Path(fname).stem}"
        out.write(f"  building {spike_target} ... ")
        out.flush()
        status, stderr, duration = _run_lake_build(project, spike_target, timeout)
        out.write(f"{status} ({duration:.1f}s)\n")
        try:
            record_lean_attempt(
                proposition_id="spike",
                status=status,
                lean_source=(SPIKE_TEMPLATE_DIR / fname).read_text(encoding="utf-8"),
                stderr=stderr[:4000] if stderr else "",
                duration_sec=duration,
                triage={"eligible": True, "estimated_difficulty": "low",
                        "reasons": ["spike validation"]},
            )
        except Exception as exc:  # noqa: BLE001
            out.write(f"    warn: could not record attempt: {exc}\n")
        if status == "verified":
            verified += 1
        elif status == "timeout":
            timed_out += 1
        else:
            failed += 1

    out.write(
        f"\nspike summary: verified={verified} failed={failed} "
        f"timeout={timed_out} (project={project})\n"
    )
    return {
        "verified": verified,
        "failed": failed,
        "timeout": timed_out,
        "skipped": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help=(
            "lake project directory (default: "
            f"{DEFAULT_PROJECT.relative_to(REPO_ROOT)})"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SEC,
        help="per-spike wallclock timeout in seconds",
    )
    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help=(
            "subset of spike .lean filenames to run "
            "(omit extension is fine; default: all five)"
        ),
    )
    args = parser.parse_args(argv)

    only = None
    if args.only:
        only = []
        for name in args.only:
            if not name.endswith(".lean"):
                name = name + ".lean"
            only.append(name)

    counts = run(project_dir=args.project_dir, timeout=args.timeout, only=only)
    if counts["verified"] >= 3:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
