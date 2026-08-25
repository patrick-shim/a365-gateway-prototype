from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from a365_agent.config import AgentSettings
from a365_agent.gateway import TelemetryClient
from a365_agent.models import Caller, ConversationContext


class FakeResponse:
    def __init__(self, status: int, payload: object | None = None) -> None:
        self.status = status
        self.body = b"" if payload is None else json.dumps(payload).encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def make_client(*, delivery_required: bool = True) -> TelemetryClient:
    return TelemetryClient(
        gateway_url="http://127.0.0.1:4318/v1/telemetry",
        dlp_url="http://127.0.0.1:4318/v1/dlp/evaluate",
        model="deployment",
        inference_endpoint="https://example.openai.azure.com/",
        caller=Caller(
            user_id="user-id",
            email="user@example.com",
            name="Example User",
            client_ip="127.0.0.1",
        ),
        channel="console",
        timeout_seconds=12.5,
        delivery_required=delivery_required,
        api_key="gateway-secret",
    )


class TelemetryClientTests(unittest.TestCase):
    def test_invalid_timeouts_are_rejected_before_caller_authentication(self) -> None:
        settings = AgentSettings(
            endpoint="https://example.openai.azure.com/",
            deployment="deployment",
            api_version="2024-12-01-preview",
            scope="scope",
            system_prompt="prompt",
        )
        with patch(
            "a365_agent.gateway.Caller.from_azure_credential"
        ) as caller_from_credential:
            for value in ("invalid", "0", "-1", "nan", "inf"):
                with (
                    self.subTest(value=value),
                    patch.dict(
                        "os.environ",
                        {
                            "OBS_GATEWAY_URL": (
                                "http://127.0.0.1:4318/v1/telemetry"
                            ),
                            "OBS_GATEWAY_TIMEOUT_SECONDS": value,
                        },
                        clear=True,
                    ),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "OBS_GATEWAY_TIMEOUT_SECONDS must be a positive finite number",
                    ):
                        TelemetryClient.from_environment(
                            credential=object(),
                            settings=settings,
                        )

        caller_from_credential.assert_not_called()

    def test_dlp_request_matches_gateway_contract(self) -> None:
        context = ConversationContext("session-id", "conversation-id")
        with patch(
            "a365_agent.gateway.urlopen",
            return_value=FakeResponse(
                200,
                {"allowed": False, "reason": "policy blocked content"},
            ),
        ) as open_url:
            decision = make_client().evaluate_content(
                content="sensitive input",
                activity="uploadText",
                context=context,
                sequence_number=3,
            )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "policy blocked content")
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:4318/v1/dlp/evaluate")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer gateway-secret")
        self.assertEqual(open_url.call_args.kwargs["timeout"], 12.5)
        self.assertEqual(
            json.loads(request.data),
            {
                "user_id": "user-id",
                "content": "sensitive input",
                "activity": "uploadText",
                "conversation_id": "conversation-id",
                "sequence_number": 3,
                "client_ip": "127.0.0.1",
            },
        )

    def test_empty_content_is_allowed_without_http_request(self) -> None:
        with patch("a365_agent.gateway.urlopen") as open_url:
            decision = make_client().evaluate_content(
                content="",
                activity="downloadText",
                context=ConversationContext("session", "conversation"),
                sequence_number=0,
            )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "Content is empty")
        open_url.assert_not_called()

    def test_invalid_dlp_response_is_rejected(self) -> None:
        with patch(
            "a365_agent.gateway.urlopen",
            return_value=FakeResponse(200, {"allowed": "yes"}),
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid DLP decision"):
                make_client().evaluate_content(
                    content="input",
                    activity="uploadText",
                    context=ConversationContext("session", "conversation"),
                    sequence_number=0,
                )

    def test_telemetry_event_contains_current_turn_but_not_credentials(self) -> None:
        event = make_client()._build_event(
            user_input="current input",
            answer="current answer",
            context=ConversationContext("session", "conversation"),
            input_tokens=11,
            output_tokens=7,
            finish_reason="stop",
        )

        self.assertEqual(event["schema_version"], "1.0")
        self.assertEqual(event["input"], "current input")
        self.assertEqual(event["output"], "current answer")
        self.assertEqual(event["usage"], {"input_tokens": 11, "output_tokens": 7})
        serialized = json.dumps(event)
        self.assertNotIn("gateway-secret", serialized)
        self.assertNotIn("system_prompt", serialized)
        self.assertNotIn("messages", serialized)

    def test_required_telemetry_wraps_delivery_failure(self) -> None:
        client = make_client(delivery_required=True)
        with patch.object(client, "_post_json", side_effect=OSError("offline")):
            with self.assertRaisesRegex(RuntimeError, "telemetry delivery failed"):
                client._send({"event_id": "event"})

    def test_optional_telemetry_warns_and_continues(self) -> None:
        client = make_client(delivery_required=False)
        with (
            patch.object(client, "_post_json", side_effect=OSError("offline")),
            patch("builtins.print") as print_mock,
        ):
            delivered = client._send({"event_id": "event"})

        self.assertFalse(delivered)
        print_mock.assert_called_once()

    def test_successful_telemetry_reports_delivery(self) -> None:
        client = make_client()
        with patch.object(client, "_post_json", return_value={}):
            delivered = client._send({"event_id": "event"})

        self.assertTrue(delivered)


if __name__ == "__main__":
    unittest.main()
