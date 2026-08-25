from __future__ import annotations

import socket
import unittest
from unittest.mock import MagicMock, patch

from obs_gateway.config import PurviewConfig
from obs_gateway.purview.graph_client import (
    _SSL_CONTEXT,
    PurviewGraphClient,
    _urlopen_transport,
)
from obs_gateway.shared.errors import (
    GraphHttpError,
    GraphResponseError,
    GraphTimeoutError,
)


def config() -> PurviewConfig:
    return PurviewConfig(
        application_id="app-id",
        app_name="Test Gateway",
        app_version="1.0",
        graph_base_url="https://graph.microsoft.com/v1.0",
        request_timeout_seconds=1.5,
        scope_cache_seconds=3600,
        enabled=True,
        fail_closed=True,
    )


class GraphClientTests(unittest.TestCase):
    @patch("obs_gateway.purview.graph_client.urlopen")
    def test_default_transport_uses_system_trust_context(
        self, mock_urlopen: MagicMock
    ) -> None:
        response = MagicMock()
        response.read.return_value = b"{}"
        response.headers = {"request-id": "graph-request-id"}
        response.status = 200
        mock_urlopen.return_value.__enter__.return_value = response

        result = _urlopen_transport(
            unittest.mock.ANY,
            1.5,
        )

        self.assertEqual(result[2], 200)
        mock_urlopen.assert_called_once_with(
            unittest.mock.ANY,
            timeout=1.5,
            context=_SSL_CONTEXT,
        )

    def test_classifies_timeout(self) -> None:
        def transport(request, timeout):
            raise socket.timeout("timed out")

        client = PurviewGraphClient(
            config(), lambda: "token", transport=transport
        )
        with self.assertRaisesRegex(
            GraphTimeoutError,
            "processContent timed out after 1.5 seconds",
        ):
            client.post_json(
                operation="processContent", path="/test", body={}
            )

    def test_rejects_non_object_json(self) -> None:
        client = PurviewGraphClient(
            config(),
            lambda: "token",
            transport=lambda request, timeout: (b"[]", {}, 200),
        )
        with self.assertRaises(GraphResponseError):
            client.post_json(operation="processContent", path="/test", body={})

    def test_rejects_error_status_from_custom_transport(self) -> None:
        client = PurviewGraphClient(
            config(),
            lambda: "token",
            transport=lambda request, timeout: (
                b'{"error": "synthetic failure"}',
                {},
                503,
            ),
        )
        with self.assertRaisesRegex(GraphHttpError, "HTTP 503"):
            client.post_json(operation="processContent", path="/test", body={})


if __name__ == "__main__":
    unittest.main()
