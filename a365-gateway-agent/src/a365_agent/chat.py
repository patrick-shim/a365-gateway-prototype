"""Interactive multi-turn Azure OpenAI chat workflow."""

from __future__ import annotations

from azure.identity import DefaultAzureCredential

from .azure_openai import build_openai_client
from .config import AgentSettings
from .gateway import TelemetryClient
from .models import ConversationContext


def run_chat() -> None:
    """Run the console chat with prompt and response DLP enforcement."""

    settings = AgentSettings.from_environment()
    credential = DefaultAzureCredential()
    client = build_openai_client(settings, credential)
    telemetry = TelemetryClient.from_environment(
        credential=credential,
        settings=settings,
    )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": settings.system_prompt}
    ]
    context = ConversationContext.new()
    sequence_number = 0

    print(
        "Azure OpenAI tourist chat. Telemetry is sent through obs_gateway. "
        "Type /exit to quit or /clear to reset."
    )
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            return

        if not user_input:
            continue
        if user_input.lower() in {"/exit", "/quit"}:
            print("Goodbye!")
            return
        if user_input.lower() == "/clear":
            messages[:] = [{"role": "system", "content": settings.system_prompt}]
            context = ConversationContext.new()
            sequence_number = 0
            print("Conversation cleared.")
            continue

        current_sequence = sequence_number
        sequence_number += 1

        prompt_decision = telemetry.evaluate_content(
            content=user_input,
            activity="uploadText",
            context=context,
            sequence_number=current_sequence,
        )
        if not prompt_decision.allowed:
            print("Blocked by Microsoft Purview DLP policy.\n")
            continue

        messages.append({"role": "user", "content": user_input})
        try:
            response = client.chat.completions.create(
                model=settings.deployment,
                messages=messages,
                max_completion_tokens=4096,
            )
            answer = response.choices[0].message.content or ""
        except Exception as exc:
            telemetry.record_failure(
                user_input=user_input,
                error=exc,
                context=context,
            )
            messages.pop()
            raise

        response_decision = telemetry.evaluate_content(
            content=answer,
            activity="downloadText",
            context=context,
            sequence_number=current_sequence,
        )
        if not response_decision.allowed:
            telemetry.record_failure(
                user_input=user_input,
                error=RuntimeError("Model response blocked by Purview DLP policy"),
                context=context,
            )
            messages.pop()
            print("The model response was blocked by Microsoft Purview DLP policy.\n")
            continue

        telemetry.record_completion(
            user_input=user_input,
            answer=answer,
            response=response,
            context=context,
        )
        messages.append({"role": "assistant", "content": answer})
        print(f"Assistant: {answer}\n")
