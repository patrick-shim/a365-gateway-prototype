from __future__ import annotations

import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from obs_gateway.config import ServerConfig
from obs_gateway.http.server import create_gateway_server
from obs_gateway.purview.types import DlpDecision, DlpEvaluation


class FakeExporter:
    def __init__(self) -> None:
        self.events = []

    def export(self, event) -> str:
        self.events.append(event)
        return event.event_id

    def flush(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


class FakeDlp:
    enabled = True

    def evaluate(self, evaluation: DlpEvaluation) -> DlpDecision:
        return DlpDecision(
            allowed=False,
            activity=evaluation.activity,
            policy_actions=(
                {
                    "action": "restrictAccess",
                    "restrictionAction": "block",
                },
            ),
            protection_scope_state="notModified",
            reason="Purview policy requires blocking",
        )


class FailingExporter(FakeExporter):
    def export(self, event) -> str:
        raise RuntimeError("internal exporter detail")


class FailingDlp:
    enabled = True

    def evaluate(self, evaluation: DlpEvaluation) -> DlpDecision:
        raise ValueError("internal DLP detail")


class HttpServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.exporter = FakeExporter()
        config = ServerConfig(
            host="127.0.0.1",
            port=0,
            api_key="gateway-secret",
            max_request_bytes=1_048_576,
        )
        self.server = create_gateway_server(
            config=config,
            exporter=self.exporter,
            dlp=FakeDlp(),
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_matches_gateway_http_contract(self) -> None:
        status, health, headers = self._request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(
            health,
            {"status": "ok", "purview_dlp_enabled": True},
        )
        self.assertTrue(headers.get("Client-Request-Id"))

        status, body, _ = self._request(
            "POST", "/v1/telemetry", {}, api_key="wrong"
        )
        self.assertEqual(status, 401)
        self.assertEqual(body, {"error": "unauthorized"})

        status, body, _ = self._request(
            "POST",
            "/v1/telemetry",
            valid_telemetry_payload(),
            api_key="gateway-secret",
        )
        self.assertEqual(status, 202)
        self.assertEqual(
            body, {"status": "exported", "event_id": "event-1"}
        )
        self.assertEqual(len(self.exporter.events), 1)

        status, body, _ = self._request(
            "POST",
            "/v1/dlp/evaluate",
            {
                "user_id": "user-1",
                "content": "synthetic content",
                "activity": "uploadText",
                "conversation_id": "conversation-1",
                "sequence_number": 0,
                "client_ip": "127.0.0.1",
            },
            api_key="gateway-secret",
        )
        self.assertEqual(status, 200)
        self.assertFalse(body["allowed"])
        self.assertTrue(body["blocked"])

    def test_rejects_invalid_dlp_request(self) -> None:
        status, body, _ = self._request(
            "POST",
            "/v1/dlp/evaluate",
            {"sequence_number": -1},
            api_key="gateway-secret",
        )
        self.assertEqual(status, 400)
        self.assertIn("sequence_number", body["error"])

    def test_redacts_unexpected_exporter_error(self) -> None:
        self.server.exporter = FailingExporter()
        with patch("obs_gateway.http.server.LOGGER"):
            status, body, _ = self._request(
                "POST",
                "/v1/telemetry",
                valid_telemetry_payload(),
                api_key="gateway-secret",
            )
        self.assertEqual(status, 500)
        self.assertEqual(body, {"error": "telemetry export failed"})

    def test_redacts_unexpected_dlp_error_and_blocks(self) -> None:
        self.server.dlp = FailingDlp()
        with patch("obs_gateway.http.server.LOGGER"):
            status, body, _ = self._request(
                "POST",
                "/v1/dlp/evaluate",
                valid_dlp_payload(),
                api_key="gateway-secret",
            )
        self.assertEqual(status, 500)
        self.assertEqual(
            body,
            {"error": "internal gateway error; activity blocked", "blocked": True},
        )

    def _request(
        self,
        method: str,
        path: str,
        body: object | None = None,
        *,
        api_key: str | None = None,
    ) -> tuple[int, dict, object]:
        data = None if body is None else json.dumps(body).encode()
        headers = {}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if api_key is not None:
            headers["Authorization"] = f"Bearer {api_key}"
        request = Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request) as response:
                return (
                    response.status,
                    json.loads(response.read()),
                    response.headers,
                )
        except HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read()), exc.headers
            finally:
                exc.close()


def valid_telemetry_payload() -> dict[str, object]:
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
        "caller": {"id": "user-1", "client_ip": "127.0.0.1"},
        "usage": {"input_tokens": 5, "output_tokens": 2},
        "finish_reason": "stop",
    }


def valid_dlp_payload() -> dict[str, object]:
    return {
        "user_id": "user-1",
        "content": "synthetic content",
        "activity": "uploadText",
        "conversation_id": "conversation-1",
        "sequence_number": 0,
        "client_ip": "127.0.0.1",
    }


if __name__ == "__main__":
    unittest.main()
