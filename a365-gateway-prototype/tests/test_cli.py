from __future__ import annotations

import unittest
from unittest.mock import patch

from obs_gateway import cli
from obs_gateway.config import (
    AgentConfig,
    AgentDetailsConfig,
    GatewayConfig,
    ObservabilityConfig,
    PurviewConfig,
    ServerConfig,
)
from obs_gateway.shared.errors import ConfigurationError


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        basic_config = patch.object(cli.logging, "basicConfig")
        basic_config.start()
        self.addCleanup(basic_config.stop)

    def test_returns_two_for_configuration_error(self) -> None:
        with (
            patch.object(
                cli,
                "load_config",
                side_effect=ConfigurationError("missing registration"),
            ),
            patch("sys.stderr"),
        ):
            self.assertEqual(cli.main([]), 2)

    def test_returns_one_for_startup_error(self) -> None:
        with (
            patch.object(cli, "load_config", return_value=object()),
            patch.object(
                cli,
                "build_runtime",
                side_effect=OSError("address already in use"),
            ),
            patch("sys.stderr"),
        ):
            self.assertEqual(cli.main([]), 1)

    def test_runs_valid_runtime(self) -> None:
        config = object()
        runtime = object()
        with (
            patch.object(cli, "load_config", return_value=config),
            patch.object(cli, "build_runtime", return_value=runtime),
            patch.object(cli, "serve") as serve_runtime,
        ):
            self.assertEqual(cli.main([]), 0)
        serve_runtime.assert_called_once_with(runtime, config)

    def test_check_config_avoids_runtime_and_prints_summary(self) -> None:
        config = _summary_config()
        with (
            patch.object(cli, "load_config", return_value=config),
            patch.object(cli, "build_runtime") as build_runtime,
            patch("builtins.print") as print_mock,
        ):
            self.assertEqual(cli.main(["--check-config"]), 0)

        build_runtime.assert_not_called()
        self.assertIn(
            "Gateway configuration is valid.",
            [call.args[0] for call in print_mock.call_args_list],
        )

    def test_forwards_custom_environment_file(self) -> None:
        config = _summary_config()
        with (
            patch.object(cli, "load_config", return_value=config) as load,
            patch("builtins.print"),
        ):
            self.assertEqual(
                cli.main(["--check-config", "--env-file", "custom.env"]),
                0,
            )
        self.assertEqual(load.call_args.args[0].name, "custom.env")


def _summary_config():
    return GatewayConfig(
        server=ServerConfig("127.0.0.1", 4318, None, 1_048_576),
        purview=PurviewConfig(
            "app-id",
            "Gateway",
            "1.0",
            "https://graph.microsoft.com/v1.0",
            15.0,
            3600.0,
            True,
            True,
        ),
        agent=AgentConfig("app-id", "blueprint-id", "tenant-id"),
        observability=ObservabilityConfig(
            AgentDetailsConfig(
                "agent-id",
                "Agent",
                "Description",
                "blueprint-id",
                "tenant-id",
            ),
            True,
            True,
            True,
            "INFO",
            False,
        ),
    )


if __name__ == "__main__":
    unittest.main()
