from __future__ import annotations

import unittest

from obs_gateway.shared.errors import ValidationError
from obs_gateway.telemetry.event import TelemetryEvent


def valid_payload() -> dict[str, object]:
    return {
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
        "caller": {
            "id": "user-1",
            "email": None,
            "name": "Test User",
            "client_ip": "127.0.0.1",
        },
        "usage": {"input_tokens": 5, "output_tokens": 2},
        "finish_reason": "stop",
    }


class TelemetryEventTests(unittest.TestCase):
    def test_parses_agent_contract(self) -> None:
        event = TelemetryEvent.from_payload(valid_payload())
        self.assertEqual(event.event_id, "event-1")
        self.assertEqual(event.caller.user_id, "user-1")
        self.assertEqual(event.endpoint.port, 443)
        self.assertEqual(event.usage.input_tokens, 5)

    def test_rejects_unsupported_schema(self) -> None:
        payload = valid_payload()
        payload["schema_version"] = "2.0"
        with self.assertRaisesRegex(
            ValidationError, "schema_version must be '1.0'"
        ):
            TelemetryEvent.from_payload(payload)

    def test_rejects_negative_tokens_and_invalid_ports(self) -> None:
        payload = valid_payload()
        payload["usage"] = {"input_tokens": -1}
        with self.assertRaises(ValidationError):
            TelemetryEvent.from_payload(payload)

    def test_rejects_non_string_metadata(self) -> None:
        for field, value in (
            ("channel", {"name": "console"}),
            ("caller.client_ip", ["127.0.0.1"]),
            ("error.type", {"name": "RuntimeError"}),
        ):
            with self.subTest(field=field):
                payload = valid_payload()
                if field == "channel":
                    payload["channel"] = value
                elif field == "caller.client_ip":
                    payload["caller"]["client_ip"] = value
                else:
                    payload["error"] = {
                        "type": value,
                        "message": "synthetic failure",
                    }
                with self.assertRaises(ValidationError):
                    TelemetryEvent.from_payload(payload)

        payload = valid_payload()
        payload["inference_endpoint"] = {
            "hostname": "example.com",
            "port": 70_000,
        }
        with self.assertRaises(ValidationError):
            TelemetryEvent.from_payload(payload)


if __name__ == "__main__":
    unittest.main()
