from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from microsoft.opentelemetry.a365.core import AgentDetails

from obs_gateway.config import AgentDetailsConfig, ObservabilityConfig
from obs_gateway.telemetry.event import TelemetryEvent
from obs_gateway.telemetry.exporter import (
    Agent365TelemetryExporter,
    create_telemetry_exporter,
)


def config(*, remote_export_enabled: bool) -> ObservabilityConfig:
    return ObservabilityConfig(
        agent=AgentDetailsConfig(
            agent_id="agent-id",
            agent_name="Test Agent",
            agent_description="Test description",
            agent_blueprint_id="blueprint-id",
            tenant_id="tenant-id",
        ),
        enabled=True,
        remote_export_enabled=remote_export_enabled,
        use_s2s_endpoint=True,
        log_level="INFO",
        console_enabled=False,
    )


def event() -> TelemetryEvent:
    return TelemetryEvent.from_payload(
        {
            "schema_version": "1.0",
            "event_id": "event-1",
            "session_id": "session-1",
            "conversation_id": "conversation-1",
            "channel": "console",
            "input": "hello",
            "output": "hi",
            "model": "gpt-4.1",
            "provider_name": "azure-openai",
            "inference_endpoint": {"hostname": "example.com", "port": 443},
            "caller": {"id": "user-1", "client_ip": "127.0.0.1"},
            "usage": {"input_tokens": 5, "output_tokens": 2},
            "finish_reason": "stop",
        }
    )


class TelemetryExporterTests(unittest.TestCase):
    @patch("obs_gateway.telemetry.exporter.Agent365TelemetryExporter")
    def test_primes_remote_token_before_configuration(
        self,
        exporter_type: MagicMock,
    ) -> None:
        tokens = MagicMock()
        exporter = create_telemetry_exporter(
            config(remote_export_enabled=True),
            tokens,
        )

        self.assertIs(exporter, exporter_type.return_value)
        tokens.refresh_observability_token.assert_called_once_with()
        exporter.configure_opentelemetry.assert_called_once_with()

    @patch("obs_gateway.telemetry.exporter.Agent365TelemetryExporter")
    def test_local_export_does_not_request_remote_token(
        self,
        exporter_type: MagicMock,
    ) -> None:
        tokens = MagicMock()
        create_telemetry_exporter(
            config(remote_export_enabled=False),
            tokens,
        )

        tokens.refresh_observability_token.assert_not_called()
        exporter_type.return_value.configure_opentelemetry.assert_called_once_with()

    def test_maps_agent_error_to_recordable_exception(self) -> None:
        exporter = Agent365TelemetryExporter(
            config(remote_export_enabled=False),
            MagicMock(),
            AgentDetails(agent_id="agent-id", tenant_id="tenant-id"),
        )
        self.assertIsNone(exporter._as_exception(event()))

        failed = TelemetryEvent.from_payload(
            {
                "schema_version": "1.0",
                "event_id": "event-2",
                "session_id": "session-1",
                "conversation_id": "conversation-1",
                "input": "hello",
                "output": "",
                "model": "gpt-4.1",
                "provider_name": "azure-openai",
                "inference_endpoint": {
                    "hostname": "example.com",
                    "port": 443,
                },
                "caller": {"id": "user-1"},
                "error": {
                    "type": "ModelError",
                    "message": "synthetic failure",
                },
            }
        )
        error = exporter._as_exception(failed)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(str(error), "ModelError: synthetic failure")


if __name__ == "__main__":
    unittest.main()