from __future__ import annotations

import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from obs_gateway.config import PurviewConfig
from obs_gateway.purview.dlp_service import DlpService
from obs_gateway.purview.graph_client import PurviewGraphClient
from obs_gateway.purview.types import DlpEvaluation
from obs_gateway.shared.errors import PurviewDlpError


def config(**overrides) -> PurviewConfig:
    values = {
        "application_id": "blueprint-app-id",
        "app_name": "Test Gateway",
        "app_version": "1.0",
        "graph_base_url": "https://graph.microsoft.com/v1.0",
        "request_timeout_seconds": 1.0,
        "scope_cache_seconds": 3600.0,
        "enabled": True,
        "fail_closed": True,
    }
    values.update(overrides)
    return PurviewConfig(**values)


def evaluation(sequence_number: int = 0) -> DlpEvaluation:
    return DlpEvaluation(
        user_id="user@example.com",
        content="synthetic content",
        activity="uploadText",
        conversation_id="conversation-1",
        sequence_number=sequence_number,
        client_ip="127.0.0.1",
    )


def scope_response() -> bytes:
    return json.dumps(
        {
            "value": [
                {
                    "activities": "uploadText,downloadText",
                    "executionMode": "evaluateInline",
                    "policyActions": [],
                }
            ]
        }
    ).encode()


class DlpServiceTests(unittest.TestCase):
    def test_enforces_inline_block_and_sends_etag(self) -> None:
        calls = []

        def transport(request, timeout):
            calls.append(request)
            if request.full_url.endswith("/protectionScopes/compute"):
                return scope_response(), {"ETag": '"policy-v1"'}, 200
            body = {
                "protectionScopeState": "notModified",
                "policyActions": [
                    {
                        "action": "restrictAccess",
                        "restrictionAction": "block",
                    }
                ],
            }
            return json.dumps(body).encode(), {}, 200

        service = self._service(transport)
        decision = service.evaluate(evaluation())
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "Purview policy requires blocking")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1].get_header("If-none-match"), '"policy-v1"')
        process_body = json.loads(calls[1].data)
        location = process_body["contentToProcess"]["protectedAppMetadata"]
        self.assertEqual(
            location["applicationLocation"]["value"], "blueprint-app-id"
        )

    def test_reuses_cached_scope(self) -> None:
        scope_calls = 0

        def transport(request, timeout):
            nonlocal scope_calls
            if request.full_url.endswith("/protectionScopes/compute"):
                scope_calls += 1
                return scope_response(), {}, 200
            return b'{"policyActions": []}', {}, 200

        service = self._service(transport)
        service.evaluate(evaluation())
        service.evaluate(evaluation(1))
        self.assertEqual(scope_calls, 1)

    def test_blocks_immediately_when_scope_requires_it(self) -> None:
        calls = 0

        def transport(request, timeout):
            nonlocal calls
            calls += 1
            body = {
                "value": [
                    {
                        "activities": "uploadText",
                        "executionMode": "evaluateInline",
                        "policyActions": [
                            {
                                "action": "restrictAccess",
                                "restrictionAction": "block",
                            }
                        ],
                    }
                ]
            }
            return json.dumps(body).encode(), {}, 200

        decision = self._service(transport).evaluate(evaluation())
        self.assertFalse(decision.allowed)
        self.assertEqual(calls, 1)

    def test_refreshes_modified_scopes_once(self) -> None:
        scope_calls = 0
        process_calls = 0

        def transport(request, timeout):
            nonlocal scope_calls, process_calls
            if request.full_url.endswith("/protectionScopes/compute"):
                scope_calls += 1
                return scope_response(), {"ETag": f'"v{scope_calls}"'}, 200
            process_calls += 1
            state = "modified" if process_calls == 1 else "notModified"
            body = {
                "protectionScopeState": state,
                "policyActions": [],
            }
            return json.dumps(body).encode(), {}, 200

        decision = self._service(transport).evaluate(evaluation())
        self.assertTrue(decision.allowed)
        self.assertEqual(scope_calls, 2)
        self.assertEqual(process_calls, 2)

    def test_shares_concurrent_scope_request(self) -> None:
        scope_calls = 0
        lock = threading.Lock()

        def transport(request, timeout):
            nonlocal scope_calls
            if request.full_url.endswith("/protectionScopes/compute"):
                with lock:
                    scope_calls += 1
                time.sleep(0.05)
                return scope_response(), {}, 200
            return b'{"policyActions": []}', {}, 200

        service = self._service(transport)
        with ThreadPoolExecutor(max_workers=4) as pool:
            decisions = list(pool.map(service.evaluate, [evaluation()] * 4))
        self.assertTrue(all(item.allowed for item in decisions))
        self.assertEqual(scope_calls, 1)

    def test_fails_closed(self) -> None:
        def transport(request, timeout):
            raise OSError("network unavailable")

        with self.assertRaises(PurviewDlpError):
            self._service(transport).evaluate(evaluation())

    def test_fails_open_when_configured(self) -> None:
        def transport(request, timeout):
            raise OSError("network unavailable")

        decision = self._service(
            transport, fail_closed=False
        ).evaluate(evaluation())
        self.assertTrue(decision.allowed)
        self.assertIn("failed open", decision.reason or "")

    def test_rejects_malformed_scope_collection(self) -> None:
        def transport(request, timeout):
            return b'{"value": {}}', {}, 200

        with self.assertRaisesRegex(
            PurviewDlpError,
            "unexpected response",
        ):
            self._service(transport).evaluate(evaluation())

    def test_rejects_malformed_process_actions(self) -> None:
        def transport(request, timeout):
            if request.full_url.endswith("/protectionScopes/compute"):
                return scope_response(), {}, 200
            return b'{"policyActions": {}}', {}, 200

        with self.assertRaisesRegex(
            PurviewDlpError,
            "unexpected response",
        ):
            self._service(transport).evaluate(evaluation())

    @staticmethod
    def _service(transport, **overrides) -> DlpService:
        settings = config(**overrides)
        graph = PurviewGraphClient(
            settings,
            lambda: "test-token",
            transport=transport,
        )
        return DlpService(settings, graph)


if __name__ == "__main__":
    unittest.main()
