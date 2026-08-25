"""Command-line parsing and top-level error handling."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .chat import run_chat
from .config import DEFAULT_SIT_FILE
from .sit import run_sit_batch


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for chat and SIT modes."""

    parser = argparse.ArgumentParser(
        description="Azure OpenAI tourist chat with Agent 365 integration"
    )
    parser.add_argument(
        "--sit",
        nargs="?",
        const=DEFAULT_SIT_FILE,
        type=Path,
        metavar="YAML_FILE",
        help=(
            "batch-evaluate synthetic SIT samples through Purview; "
            f"defaults to {DEFAULT_SIT_FILE.name}"
        ),
    )
    parser.add_argument(
        "--ai",
        action="store_true",
        help=(
            "with --sit, run allowed samples through Azure OpenAI, response "
            "DLP, and A365 telemetry"
        ),
    )
    args = parser.parse_args(argv)
    if args.ai and args.sit is None:
        parser.error("--ai requires --sit")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    """Run the requested mode and map failures to stable process exit codes."""

    try:
        args = parse_args(argv)
        if args.sit is not None:
            return run_sit_batch(
                args.sit.expanduser().resolve(),
                use_ai=args.ai,
            )
        run_chat()
    except RuntimeError as exc:
        print(f"Configuration or telemetry error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Azure OpenAI request failed: {exc}", file=sys.stderr)
        return 1
    return 0
