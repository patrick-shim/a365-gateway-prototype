from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from obs_gateway.config import load_config
from obs_gateway.shared.errors import ConfigurationError


REQUIRED_ENV = """
AGENT_ID=blueprint-id
CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID=connection-client-id
CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET=synthetic-secret
CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID=tenant-id
CONNECTIONS__SERVICE_CONNECTION__SETTINGS__SCOPES=api://scope/.default
AGENTAPPLICATION__USERAUTHORIZATION__HANDLERS__AGENTIC__SETTINGS__TYPE=agentic
AGENTAPPLICATION__USERAUTHORIZATION__HANDLERS__AGENTIC__SETTINGS__ALT_BLUEPRINT_NAME=test-blueprint
AGENTAPPLICATION__USERAUTHORIZATION__HANDLERS__AGENTIC__SETTINGS__SCOPES=api://scope/.default
CONNECTIONSMAP__0__SERVICEURL=*
CONNECTIONSMAP__0__CONNECTION=SERVICE_CONNECTION
AGENT365OBSERVABILITY__AGENTID=agent-id
AGENT365OBSERVABILITY__AGENTNAME=Test Agent
AGENT365OBSERVABILITY__AGENTDESCRIPTION=Test description
AGENT365OBSERVABILITY__AGENTBLUEPRINTID=blueprint-id
AGENT365OBSERVABILITY__TENANTID=tenant-id
"""


class ConfigTests(unittest.TestCase):
    def test_loads_typed_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(REQUIRED_ENV, encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                config = load_config(env_file)
        self.assertEqual(config.server.port, 4318)
        self.assertEqual(config.purview.application_id, "agent-id")
        self.assertEqual(config.purview.request_timeout_seconds, 15.0)
        self.assertEqual(config.agent.agent_id, "agent-id")
        self.assertEqual(config.agent.blueprint_id, "blueprint-id")
        self.assertEqual(config.observability.agent.agent_id, "agent-id")

    def test_explicit_purview_application_id_overrides_agent_instance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                REQUIRED_ENV + "PURVIEW_APPLICATION_ID=policy-app-id\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                config = load_config(env_file)
        self.assertEqual(config.purview.application_id, "policy-app-id")

    def test_rejects_invalid_boolean(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                REQUIRED_ENV + "PURVIEW_DLP_ENABLED=perhaps\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(
                    ConfigurationError, "must be true or false"
                ):
                    load_config(env_file)

    def test_lists_missing_registration_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "PURVIEW_DLP_ENABLED=true\n"
                "ENABLE_A365_OBSERVABILITY_EXPORTER=true\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(
                    ConfigurationError,
                    "AGENT_ID.*SERVICE_CONNECTION",
                ):
                    load_config(env_file)

    def test_registration_settings_remain_required_when_features_disabled(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "PURVIEW_DLP_ENABLED=false\n"
                "ENABLE_A365_OBSERVABILITY=false\n"
                "ENABLE_A365_OBSERVABILITY_EXPORTER=false\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(
                    ConfigurationError,
                    "SERVICE_CONNECTION",
                ):
                    load_config(env_file)

    def test_rejects_non_finite_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                REQUIRED_ENV + "PURVIEW_TIMEOUT_SECONDS=nan\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(
                    ConfigurationError,
                    "finite number",
                ):
                    load_config(env_file)

    def test_requires_api_key_for_non_loopback_listener(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                REQUIRED_ENV + "OBS_GATEWAY_HOST=0.0.0.0\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(
                    ConfigurationError,
                    "OBS_GATEWAY_API_KEY",
                ):
                    load_config(env_file)

    def test_allows_protected_non_loopback_listener(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                REQUIRED_ENV
                + "OBS_GATEWAY_HOST=0.0.0.0\n"
                + "OBS_GATEWAY_API_KEY=synthetic-gateway-key\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                config = load_config(env_file)
        self.assertEqual(config.server.host, "0.0.0.0")

    def test_rejects_remote_export_when_observability_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                REQUIRED_ENV
                + "ENABLE_A365_OBSERVABILITY=false\n"
                + "ENABLE_A365_OBSERVABILITY_EXPORTER=true\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(
                    ConfigurationError,
                    "cannot be true",
                ):
                    load_config(env_file)


if __name__ == "__main__":
    unittest.main()
