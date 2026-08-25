from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from a365_agent import sit
from a365_agent.config import AgentSettings
from a365_agent.models import DlpDecision, SitSample


SETTINGS = AgentSettings(
    endpoint="https://example.openai.azure.com/",
    deployment="deployment",
    api_version="2024-12-01-preview",
    scope="https://cognitiveservices.azure.com/.default",
    system_prompt="System prompt",
)


class SitTests(unittest.TestCase):
    def test_loads_default_and_per_sample_expected_actions(self) -> None:
        document = """\
expected_action: block
samples:
  - id: blocked-sample
    type: synthetic-secret
    content: should be blocked
  - id: allowed-sample
    type: public-text
    content: should be allowed
    expected_action: allow
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "samples.yaml"
            path.write_text(document, encoding="utf-8")
            samples = sit.load_sit_samples(path)

        self.assertEqual(
            [sample.expected_action for sample in samples],
            ["block", "allow"],
        )

    def test_rejects_duplicate_sample_ids(self) -> None:
        document = """\
samples:
  - id: duplicate
    type: one
    content: first
  - id: duplicate
    type: two
    content: second
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "samples.yaml"
            path.write_text(document, encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "Duplicate SIT sample id"):
                sit.load_sit_samples(path)

    def test_dlp_only_batch_never_builds_openai_client(self) -> None:
        sample = SitSample("sample", "synthetic", "content", "block")
        gateway = MagicMock()
        gateway.evaluate_content.return_value = DlpDecision(False, "blocked")

        with (
            patch.object(sit, "load_sit_samples", return_value=[sample]),
            patch.object(sit.AgentSettings, "from_environment", return_value=SETTINGS),
            patch.object(sit, "DefaultAzureCredential", return_value=object()),
            patch.object(sit, "build_openai_client") as build_client,
            patch.object(
                sit.TelemetryClient,
                "from_environment",
                return_value=gateway,
            ),
            patch("builtins.print"),
        ):
            exit_code = sit.run_sit_batch(Path("samples.yaml"))

        self.assertEqual(exit_code, 0)
        build_client.assert_not_called()
        gateway.record_completion.assert_not_called()
        gateway.record_failure.assert_not_called()

    def test_end_to_end_batch_exports_allowed_completion(self) -> None:
        sample = SitSample("sample", "public", "content", "allow")
        gateway = MagicMock()
        gateway.evaluate_content.side_effect = [
            DlpDecision(True, None),
            DlpDecision(True, None),
        ]
        response = MagicMock()
        response.choices[0].message.content = "answer"
        client = MagicMock()
        client.chat.completions.create.return_value = response

        with (
            patch.object(sit, "load_sit_samples", return_value=[sample]),
            patch.object(sit.AgentSettings, "from_environment", return_value=SETTINGS),
            patch.object(sit, "DefaultAzureCredential", return_value=object()),
            patch.object(sit, "build_openai_client", return_value=client),
            patch.object(
                sit.TelemetryClient,
                "from_environment",
                return_value=gateway,
            ),
            patch("builtins.print"),
        ):
            exit_code = sit.run_sit_batch(Path("samples.yaml"), use_ai=True)

        self.assertEqual(exit_code, 0)
        gateway.record_completion.assert_called_once()
        gateway.record_failure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
