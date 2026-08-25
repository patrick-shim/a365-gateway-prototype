from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from a365_agent.config import AgentSettings, env_is_true


VALID_ENV = """\
AZURE_OPENAI_ENDPOINT=https://example.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=test-deployment
AZURE_OPENAI_API_VERSION=2024-12-01-preview
AZURE_OPENAI_SCOPE=https://cognitiveservices.azure.com/.default
AZURE_OPENAI_SYSTEM_PROMPT=Test system prompt
"""


class AgentSettingsTests(unittest.TestCase):
    def test_loads_required_settings_from_explicit_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(VALID_ENV, encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                settings = AgentSettings.from_environment(env_file)

        self.assertEqual(settings.deployment, "test-deployment")
        self.assertEqual(settings.system_prompt, "Test system prompt")

    def test_process_environment_takes_precedence_over_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(VALID_ENV, encoding="utf-8")
            with patch.dict(
                os.environ,
                {"AZURE_OPENAI_DEPLOYMENT": "environment-deployment"},
                clear=True,
            ):
                settings = AgentSettings.from_environment(env_file)

        self.assertEqual(settings.deployment, "environment-deployment")

    def test_rejects_missing_environment_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / ".env"
            with self.assertRaisesRegex(RuntimeError, "Environment file not found"):
                AgentSettings.from_environment(missing)

    def test_rejects_empty_required_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                VALID_ENV.replace("test-deployment", ""),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "AZURE_OPENAI_DEPLOYMENT",
                ):
                    AgentSettings.from_environment(env_file)

    def test_boolean_parser_accepts_only_documented_true_values(self) -> None:
        for value in ("1", "true", "TRUE", "yes", "on"):
            with self.subTest(value=value), patch.dict(
                os.environ,
                {"FLAG": value},
                clear=True,
            ):
                self.assertTrue(env_is_true("FLAG", False))

        with patch.dict(os.environ, {"FLAG": "false"}, clear=True):
            self.assertFalse(env_is_true("FLAG", True))


if __name__ == "__main__":
    unittest.main()
