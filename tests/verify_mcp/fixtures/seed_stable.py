from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    print(f"seed={args.seed}")
    print("test_acc=0.875")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
