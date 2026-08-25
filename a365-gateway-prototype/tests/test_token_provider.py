from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from obs_gateway.auth.token_provider import (
    MICROSOFT_GRAPH_SCOPE,
    OBSERVABILITY_SCOPE,
    MsalAgentTokenProvider,
    create_token_provider,
)
from obs_gateway.config import AgentConfig


class FakeConnection:
    def __init__(self, assertion: str | None = "agentic-assertion") -> None:
        self.assertion = assertion
        self.calls: list[tuple[str, str]] = []

    async def get_agentic_application_token(
        self,
        tenant_id: str,
        agent_id: str,
    ) -> str | None:
        self.calls.append((tenant_id, agent_id))
        return self.assertion


class TokenProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = FakeConnection()
        self.manager = MagicMock()
        self.manager.get_connection.return_value = self.connection
        self.agent = AgentConfig(
            agent_id="application-id",
            blueprint_id="blueprint-id",
            tenant_id="tenant-id",
        )

    @patch("obs_gateway.auth.token_provider.MsalConnectionManager")
    @patch("obs_gateway.auth.token_provider.load_configuration_from_env")
    def test_factory_passes_generated_sdk_configuration_unchanged(
        self,
        load_configuration: MagicMock,
        manager_type: MagicMock,
    ) -> None:
        sdk_config = {
            "AGENTAPPLICATION": {"USERAUTHORIZATION": {}},
            "CONNECTIONS": {"SERVICE_CONNECTION": {"SETTINGS": {}}},
            "CONNECTIONSMAP": [
                {"SERVICEURL": "*", "CONNECTION": "SERVICE_CONNECTION"}
            ],
        }
        load_configuration.return_value = sdk_config

        provider = create_token_provider(self.agent)

        manager_type.assert_called_once_with(**sdk_config)
        self.assertIsInstance(provider, MsalAgentTokenProvider)

    @patch("obs_gateway.auth.token_provider.ConfidentialClientApplication")
    def test_acquires_graph_and_observability_scopes(
        self,
        app_type: MagicMock,
    ) -> None:
        app_type.return_value.acquire_token_for_client.side_effect = [
            {"access_token": "graph-token"},
            {"access_token": "observability-token"},
        ]
        provider = MsalAgentTokenProvider(self.manager, self.agent)

        self.assertEqual(provider.get_graph_access_token(), "graph-token")
        provider.refresh_observability_token()

        self.assertEqual(
            app_type.return_value.acquire_token_for_client.call_args_list[0]
            .kwargs["scopes"],
            [MICROSOFT_GRAPH_SCOPE],
        )
        self.assertEqual(
            app_type.return_value.acquire_token_for_client.call_args_list[1]
            .kwargs["scopes"],
            [OBSERVABILITY_SCOPE],
        )
        self.assertEqual(
            provider.resolve_observability_token(
                "application-id",
                "tenant-id",
            ),
            "observability-token",
        )
        self.assertEqual(
            self.connection.calls,
            [
                ("tenant-id", "application-id"),
                ("tenant-id", "application-id"),
            ],
        )
        self.assertTrue(app_type.call_args_list)
        self.assertTrue(
            all(
                call.kwargs["client_id"] == "application-id"
                for call in app_type.call_args_list
            )
        )

    def test_rejects_missing_agentic_assertion(self) -> None:
        self.connection.assertion = None
        provider = MsalAgentTokenProvider(self.manager, self.agent)
        with self.assertRaisesRegex(RuntimeError, "application token"):
            provider.get_graph_access_token()

    @patch("obs_gateway.auth.token_provider.ConfidentialClientApplication")
    def test_surfaces_scoped_token_error(self, app_type: MagicMock) -> None:
        app_type.return_value.acquire_token_for_client.return_value = {
            "error": "invalid_client",
            "error_description": "synthetic exchange failure",
        }
        provider = MsalAgentTokenProvider(self.manager, self.agent)
        with self.assertRaisesRegex(RuntimeError, "synthetic exchange failure"):
            provider.get_graph_access_token()


if __name__ == "__main__":
    unittest.main()