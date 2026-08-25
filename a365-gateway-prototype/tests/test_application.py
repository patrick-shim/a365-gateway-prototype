from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from obs_gateway.application import GatewayRuntime, build_runtime, serve
from obs_gateway.config import (
    AgentConfig,
    AgentDetailsConfig,
    GatewayConfig,
    ObservabilityConfig,
    PurviewConfig,
    ServerConfig,
)


def config() -> GatewayConfig:
    agent = AgentConfig(
        agent_id="application-id",
        blueprint_id="blueprint-id",
        tenant_id="tenant-id",
    )
    return GatewayConfig(
        server=ServerConfig(
            host="127.0.0.1",
            port=4318,
            api_key=None,
            max_request_bytes=1_048_576,
        ),
        purview=PurviewConfig(
            application_id="application-id",
            app_name="Test Gateway",
            app_version="1.0",
            graph_base_url="https://graph.microsoft.com/v1.0",
            request_timeout_seconds=15.0,
            scope_cache_seconds=3600.0,
            enabled=True,
            fail_closed=True,
        ),
        agent=agent,
        observability=ObservabilityConfig(
            agent=AgentDetailsConfig(
                agent_id="observability-agent-id",
                agent_name="Test Agent",
                agent_description="Test description",
                agent_blueprint_id="blueprint-id",
                tenant_id="tenant-id",
            ),
            enabled=True,
            remote_export_enabled=True,
            use_s2s_endpoint=True,
            log_level="INFO",
            console_enabled=False,
        ),
    )


class GatewayApplicationTests(unittest.TestCase):
    @patch("obs_gateway.application.create_gateway_server")
    @patch("obs_gateway.application.create_telemetry_exporter")
    @patch("obs_gateway.application.DlpService")
    @patch("obs_gateway.application.PurviewGraphClient")
    @patch("obs_gateway.application.create_token_provider")
    def test_builds_dependency_graph(
        self,
        create_tokens: MagicMock,
        graph_type: MagicMock,
        dlp_type: MagicMock,
        create_exporter: MagicMock,
        create_server: MagicMock,
    ) -> None:
        settings = config()
        runtime = build_runtime(settings)

        create_tokens.assert_called_once_with(settings.agent)
        graph_type.assert_called_once_with(
            settings.purview,
            create_tokens.return_value.get_graph_access_token,
        )
        dlp_type.assert_called_once_with(
            settings.purview,
            graph_type.return_value,
        )
        create_exporter.assert_called_once_with(
            settings.observability,
            create_tokens.return_value,
        )
        create_server.assert_called_once_with(
            config=settings.server,
            exporter=create_exporter.return_value,
            dlp=dlp_type.return_value,
        )
        self.assertIs(runtime.server, create_server.return_value)

    @patch("obs_gateway.application.create_gateway_server")
    @patch("obs_gateway.application.create_telemetry_exporter")
    @patch("obs_gateway.application.DlpService")
    @patch("obs_gateway.application.PurviewGraphClient")
    @patch("obs_gateway.application.create_token_provider")
    def test_shuts_down_exporter_when_server_binding_fails(
        self,
        create_tokens: MagicMock,
        graph_type: MagicMock,
        dlp_type: MagicMock,
        create_exporter: MagicMock,
        create_server: MagicMock,
    ) -> None:
        create_server.side_effect = OSError("address already in use")
        with self.assertRaises(OSError):
            build_runtime(config())
        create_exporter.return_value.shutdown.assert_called_once_with()

    def test_serve_closes_resources_after_keyboard_interrupt(self) -> None:
        server = MagicMock()
        server.server_address = ("127.0.0.1", 4318)
        server.serve_forever.side_effect = KeyboardInterrupt
        exporter = MagicMock()
        runtime = GatewayRuntime(server=server, exporter=exporter)

        serve(runtime, config())

        server.server_close.assert_called_once_with()
        exporter.shutdown.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
