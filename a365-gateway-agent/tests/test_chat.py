from __future__ import annotations

import unittest
from copy import deepcopy
from unittest.mock import MagicMock, patch

from a365_agent import chat
from a365_agent.config import AgentSettings
from a365_agent.models import DlpDecision


SETTINGS = AgentSettings(
    endpoint="https://example.openai.azure.com/",
    deployment="deployment",
    api_version="2024-12-01-preview",
    scope="https://cognitiveservices.azure.com/.default",
    system_prompt="System prompt",
)


def completion(answer: str) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = answer
    response.choices[0].finish_reason = "stop"
    response.usage.prompt_tokens = 10
    response.usage.completion_tokens = 5
    return response


class ChatWorkflowTests(unittest.TestCase):
    def test_successful_turn_enforces_both_dlp_boundaries(self) -> None:
        credential = object()
        client = MagicMock()
        response = completion("Safe answer")
        client.chat.completions.create.return_value = response
        telemetry = MagicMock()
        telemetry.evaluate_content.side_effect = [
            DlpDecision(True, None),
            DlpDecision(True, None),
        ]

        with (
            patch.object(chat.AgentSettings, "from_environment", return_value=SETTINGS),
            patch.object(chat, "DefaultAzureCredential", return_value=credential),
            patch.object(chat, "build_openai_client", return_value=client),
            patch.object(
                chat.TelemetryClient,
                "from_environment",
                return_value=telemetry,
            ),
            patch("builtins.input", side_effect=["Safe prompt", "/exit"]),
            patch("builtins.print"),
        ):
            chat.run_chat()

        activities = [
            call.kwargs["activity"]
            for call in telemetry.evaluate_content.call_args_list
        ]
        self.assertEqual(activities, ["uploadText", "downloadText"])
        telemetry.record_completion.assert_called_once_with(
            user_input="Safe prompt",
            answer="Safe answer",
            response=response,
            context=telemetry.evaluate_content.call_args_list[0].kwargs["context"],
        )
        telemetry.record_failure.assert_not_called()

    def test_prompt_block_never_calls_azure_openai(self) -> None:
        client = MagicMock()
        telemetry = MagicMock()
        telemetry.evaluate_content.return_value = DlpDecision(False, "blocked")

        with (
            patch.object(chat.AgentSettings, "from_environment", return_value=SETTINGS),
            patch.object(chat, "DefaultAzureCredential", return_value=object()),
            patch.object(chat, "build_openai_client", return_value=client),
            patch.object(
                chat.TelemetryClient,
                "from_environment",
                return_value=telemetry,
            ),
            patch("builtins.input", side_effect=["Blocked prompt", "/exit"]),
            patch("builtins.print"),
        ):
            chat.run_chat()

        client.chat.completions.create.assert_not_called()
        telemetry.record_completion.assert_not_called()
        telemetry.record_failure.assert_not_called()

    def test_blocked_response_rolls_back_user_turn_from_history(self) -> None:
        client = MagicMock()
        snapshots: list[list[dict[str, str]]] = []
        responses = iter([completion("Blocked answer"), completion("Safe answer")])

        def create_completion(**kwargs: object) -> MagicMock:
            snapshots.append(deepcopy(kwargs["messages"]))
            return next(responses)

        client.chat.completions.create.side_effect = create_completion
        telemetry = MagicMock()
        telemetry.evaluate_content.side_effect = [
            DlpDecision(True, None),
            DlpDecision(False, "blocked"),
            DlpDecision(True, None),
            DlpDecision(True, None),
        ]

        with (
            patch.object(chat.AgentSettings, "from_environment", return_value=SETTINGS),
            patch.object(chat, "DefaultAzureCredential", return_value=object()),
            patch.object(chat, "build_openai_client", return_value=client),
            patch.object(
                chat.TelemetryClient,
                "from_environment",
                return_value=telemetry,
            ),
            patch(
                "builtins.input",
                side_effect=["First prompt", "Second prompt", "/exit"],
            ),
            patch("builtins.print"),
        ):
            chat.run_chat()

        self.assertEqual(
            snapshots[1],
            [
                {"role": "system", "content": "System prompt"},
                {"role": "user", "content": "Second prompt"},
            ],
        )
        telemetry.record_failure.assert_called_once()
        telemetry.record_completion.assert_called_once()


if __name__ == "__main__":
    unittest.main()
