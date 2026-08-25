"""Synthetic sensitive-information test loading and batch execution."""

from __future__ import annotations

from pathlib import Path

import yaml
from azure.identity import DefaultAzureCredential

from .azure_openai import build_openai_client
from .config import AgentSettings
from .gateway import TelemetryClient
from .models import ConversationContext, SitSample


def load_sit_samples(path: Path) -> list[SitSample]:
    """Load and validate every synthetic SIT sample from a YAML file."""

    if not path.is_file():
        raise RuntimeError(f"SIT sample file not found: {path}")
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RuntimeError(f"Invalid SIT YAML in {path}: {exc}") from exc

    if not isinstance(document, dict):
        raise RuntimeError("SIT YAML must contain a top-level object")
    raw_samples = document.get("samples")
    if not isinstance(raw_samples, list) or not raw_samples:
        raise RuntimeError("SIT YAML must contain a non-empty 'samples' list")

    default_action = str(document.get("expected_action", "block")).lower()
    samples: list[SitSample] = []
    seen_ids: set[str] = set()
    for position, item in enumerate(raw_samples, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(f"SIT sample {position} must be an object")

        sample_id = str(item.get("id", "")).strip()
        sit_type = str(item.get("type", "")).strip()
        content = str(item.get("content", "")).strip()
        expected_action = str(
            item.get("expected_action", default_action)
        ).strip().lower()
        if not sample_id or not sit_type or not content:
            raise RuntimeError(
                f"SIT sample {position} requires non-empty id, type, and content"
            )
        if sample_id in seen_ids:
            raise RuntimeError(f"Duplicate SIT sample id: {sample_id}")
        if expected_action not in {"allow", "block"}:
            raise RuntimeError(
                f"SIT sample {sample_id} expected_action must be allow or block"
            )

        seen_ids.add(sample_id)
        samples.append(
            SitSample(
                sample_id=sample_id,
                sit_type=sit_type,
                content=content,
                expected_action=expected_action,
            )
        )
    return samples


def run_sit_batch(path: Path, *, use_ai: bool = False) -> int:
    """Evaluate synthetic samples, optionally using the complete AI turn path."""

    samples = load_sit_samples(path)
    settings = AgentSettings.from_environment()
    credential = DefaultAzureCredential()
    client = build_openai_client(settings, credential) if use_ai else None
    gateway = TelemetryClient.from_environment(
        credential=credential,
        settings=settings,
    )
    context = ConversationContext.new()
    matched = 0
    mismatches: list[str] = []
    errors: list[str] = []
    ai_calls = 0
    ai_completions = 0
    response_blocks = 0

    print(f"Evaluating {len(samples)} synthetic SIT samples from {path}.")
    if use_ai:
        print(
            "End-to-end mode enabled: samples allowed by prompt DLP will call "
            "Azure OpenAI, pass through response DLP, and export telemetry."
        )
    else:
        print("DLP-only mode: Azure OpenAI will not be called.")

    for sequence_number, sample in enumerate(samples):
        try:
            decision = gateway.evaluate_content(
                content=sample.content,
                activity="uploadText",
                context=context,
                sequence_number=sequence_number,
            )
            actual_action = "allow" if decision.allowed else "block"
            if actual_action == sample.expected_action:
                matched += 1
            else:
                mismatches.append(
                    f"{sample.sample_id} ({sample.sit_type}): "
                    f"expected {sample.expected_action}, received {actual_action}"
                )

            if use_ai and decision.allowed:
                assert client is not None
                ai_calls += 1
                messages = [
                    {"role": "system", "content": settings.system_prompt},
                    {"role": "user", "content": sample.content},
                ]
                try:
                    response = client.chat.completions.create(
                        model=settings.deployment,
                        messages=messages,
                        max_completion_tokens=4096,
                    )
                    answer = response.choices[0].message.content or ""
                except Exception as exc:
                    gateway.record_failure(
                        user_input=sample.content,
                        error=exc,
                        context=context,
                    )
                    raise

                response_decision = gateway.evaluate_content(
                    content=answer,
                    activity="downloadText",
                    context=context,
                    sequence_number=sequence_number,
                )
                if not response_decision.allowed:
                    response_blocks += 1
                    gateway.record_failure(
                        user_input=sample.content,
                        error=RuntimeError(
                            "Model response blocked by Purview DLP policy"
                        ),
                        context=context,
                    )
                else:
                    gateway.record_completion(
                        user_input=sample.content,
                        answer=answer,
                        response=response,
                        context=context,
                    )
                    ai_completions += 1
        except Exception as exc:
            errors.append(
                f"{sample.sample_id} ({sample.sit_type}): {type(exc).__name__}: {exc}"
            )

        completed = sequence_number + 1
        if completed % 25 == 0 or completed == len(samples):
            print(
                f"Progress: {completed}/{len(samples)} "
                f"(matched={matched}, mismatched={len(mismatches)}, "
                f"errors={len(errors)}, ai_calls={ai_calls})"
            )

    print(
        f"SIT batch complete: {matched} matched, "
        f"{len(mismatches)} mismatched, {len(errors)} errors."
    )
    if use_ai:
        print(
            f"AI results: {ai_calls} calls, {ai_completions} completed and "
            f"exported, {response_blocks} responses blocked."
        )
    for problem in mismatches + errors:
        print(f"- {problem}")
    return 0 if not mismatches and not errors else 1
