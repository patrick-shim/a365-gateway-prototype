"""Token acquisition shared by telemetry export and Purview Graph."""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Protocol

from microsoft_agents.activity import load_configuration_from_env
from microsoft_agents.authentication.msal import MsalConnectionManager
from msal import ConfidentialClientApplication

from ..config import AgentConfig


OBSERVABILITY_SCOPE = "api://9b975845-388f-4429-889e-eab1ef63949c/.default"
MICROSOFT_GRAPH_SCOPE = "https://graph.microsoft.com/.default"


class AgentTokenProvider(Protocol):
    def get_graph_access_token(self) -> str: ...

    def refresh_observability_token(self) -> None: ...

    def resolve_observability_token(
        self, agent_id: str, tenant_id: str
    ) -> str | None: ...


def create_token_provider(agent: AgentConfig) -> AgentTokenProvider:
    manager = MsalConnectionManager(**load_configuration_from_env(os.environ))
    return MsalAgentTokenProvider(manager, agent)


class MsalAgentTokenProvider:
    def __init__(
        self,
        connection_manager: MsalConnectionManager,
        agent: AgentConfig,
    ) -> None:
        self._connection_manager = connection_manager
        self._agent = agent
        self._tokens: dict[str, str] = {}
        self._token_lock = threading.Lock()

    def get_graph_access_token(self) -> str:
        return self._acquire_access_token(MICROSOFT_GRAPH_SCOPE)

    def refresh_observability_token(self) -> None:
        self._acquire_access_token(OBSERVABILITY_SCOPE)

    def resolve_observability_token(
        self, agent_id: str, tenant_id: str
    ) -> str | None:
        return self._tokens.get(
            self._token_key(agent_id, tenant_id, OBSERVABILITY_SCOPE)
        )

    def _acquire_access_token(self, scope: str) -> str:
        # Serialize the two-stage assertion exchange because telemetry and DLP
        # requests can arrive on different HTTP worker threads.
        with self._token_lock:
            connection = self._connection_manager.get_connection(
                "SERVICE_CONNECTION"
            )
            agentic_token = asyncio.run(
                connection.get_agentic_application_token(
                    self._agent.tenant_id,
                    self._agent.agent_id,
                )
            )
            if not agentic_token:
                raise RuntimeError(
                    "Unable to acquire the Agent 365 application token"
                )

            app = ConfidentialClientApplication(
                client_id=self._agent.agent_id,
                authority=(
                    "https://login.microsoftonline.com/"
                    f"{self._agent.tenant_id}"
                ),
                client_credential={
                    "client_assertion": lambda: agentic_token
                },
            )
            result = app.acquire_token_for_client(scopes=[scope])
            access_token = result.get("access_token")
            if not access_token:
                detail = (
                    result.get("error_description")
                    or result.get("error")
                    or "unknown error"
                )
                raise RuntimeError(
                    f"Unable to acquire the Agent 365 scoped token: {detail}"
                )

            self._tokens[
                self._token_key(
                    self._agent.agent_id,
                    self._agent.tenant_id,
                    scope,
                )
            ] = access_token
            return access_token

    @staticmethod
    def _token_key(agent_id: str, tenant_id: str, scope: str) -> str:
        return f"{agent_id}:{tenant_id}:{scope}"
