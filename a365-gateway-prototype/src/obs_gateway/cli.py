"""Gateway process entry point and top-level error handling."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .application import build_runtime, serve
from .config import ENV_FILE, GatewayConfig, load_config
from .shared.errors import ConfigurationError


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse gateway startup and validation options."""

    parser = argparse.ArgumentParser(
        description=(
            "Agent 365 observability and Microsoft Purview DLP gateway"
        )
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ENV_FILE,
        metavar="PATH",
        help=f"configuration file (default: {ENV_FILE})",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="validate configuration without acquiring tokens or starting HTTP",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Load configuration, assemble the gateway, and serve requests."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        args = parse_args(argv)
        config = load_config(args.env_file.expanduser().resolve())
        if args.check_config:
            _print_config_summary(config)
            return 0
        runtime = build_runtime(config)
        serve(runtime, config)
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Gateway startup failed: {exc}", file=sys.stderr)
        return 1
    return 0


def _print_config_summary(config: GatewayConfig) -> None:
    print("Gateway configuration is valid.")
    print(f"HTTP listener: {config.server.host}:{config.server.port}")
    print(f"HTTP API key configured: {config.server.api_key is not None}")
    print(f"Purview DLP enabled: {config.purview.enabled}")
    print(f"Purview fail closed: {config.purview.fail_closed}")
    print(f"Agent 365 observability enabled: {config.observability.enabled}")
    print(
        "Agent 365 remote export enabled: "
        f"{config.observability.remote_export_enabled}"
    )
