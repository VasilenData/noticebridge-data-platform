"""Run with python -m noticebridge build|verify --source FILE --output FILE."""

import argparse
import json
import sys
from pathlib import Path

from .engine import ContractError
from .exercise import run_exercise
from .publish import build_to_path, verify_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile a bounded TED capture into an inspectable release."
    )
    parser.add_argument("command", choices=("build", "verify", "exercise"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command != "exercise" and args.source is None:
        parser.error("--source is required for build and verify")
    try:
        if args.command == "exercise":
            result = run_exercise(args.output)
        else:
            action = build_to_path if args.command == "build" else verify_path
            result = action(args.source, args.output)
    except (ContractError, OSError) as exc:
        print(f"Publication refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
