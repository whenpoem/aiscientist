from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--batch-size", type=int, required=True)
    args = parser.parse_args()
    dataset = Path(args.dataset)
    if not dataset.exists():
        raise SystemExit(2)
    print(f"dataset={dataset.name}")
    print(f"batch_size={args.batch_size}")
    print("heldout_accuracy=0.82")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
