"""Run deterministic Bradley-Terry calibration diagnostics and print JSON."""

from __future__ import annotations

import argparse
import json

from memory_mcp.bt_simulation import simulate_bt_diagnostics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=1000)
    parser.add_argument("--comparisons-per-pair", type=int, default=12)
    parser.add_argument("--seed", type=int, default=20260713)
    parser.add_argument("--true-strengths", type=float, nargs="+", default=(-0.8, 0.0, 0.8))
    parser.add_argument("--prune-threshold", type=float, default=0.0)
    parser.add_argument("--min-comparisons", type=int, default=6)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = simulate_bt_diagnostics(
        true_strengths=args.true_strengths,
        trials=args.trials,
        comparisons_per_pair=args.comparisons_per_pair,
        seed=args.seed,
        prune_threshold=args.prune_threshold,
        min_comparisons=args.min_comparisons,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
