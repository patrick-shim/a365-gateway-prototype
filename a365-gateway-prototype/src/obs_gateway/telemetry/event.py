"""Validated representation of the agent-to-gateway telemetry contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..shared.errors import ValidationError


SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class Caller:
    user_id: str
    email: str | None
    name: str | None
    client_ip: str

    @classmethod
    def from_payload(cls, data: object) -> Caller:
        if not isinstance(data, dict):
            raise ValidationError("caller must be an object")
        return cls(
            user_id=_required_string(data, "id"),
            email=_optional_string(data.get("email"), "caller.email"),
            name=_optional_string(data.get("name"), "caller.name"),
            client_ip=_string_or_default(
                data.get("client_ip"),
                "caller.client_ip",
                "127.0.0.1",
            ),
        )


@dataclass(frozen=True)
class InferenceEndpoint:
    hostname: str
    port: int

    @classmethod
    def from_payload(cls, data: object) -> InferenceEndpoint:
        if not isinstance(data, dict):
            raise ValidationError("inference_endpoint must be an object")
        port = data.get("port")
        if isinstance(port, bool) or not isinstance(port, int):
            raise ValidationError("inference_endpoint.port must be an integer")
        if not 1 <= port <= 65_535:
            raise ValidationError(
                "inference_endpoint.port must be between 1 and 65535"
            )
        return cls(hostname=_required_string(data, "hostname"), port=port)


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None
    output_tokens: int | None

    @classmethod
    def from_payload(cls, data: object) -> TokenUsage:
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ValidationError("usage must be an object")
        return cls(
            input_tokens=_optional_token_count(
                data.get("input_tokens"), "usage.input_tokens"
            ),
            output_tokens=_optional_token_count(
                data.get("output_tokens"), "usage.output_tokens"
            ),
        )


@dataclass(frozen=True)
class ErrorDetails:
    error_type: str
    message: str

    @classmethod
    def from_payload(cls, data: object) -> ErrorDetails | None:
        if data is None:
            return None
        if not isinstance(data, dict):
            raise ValidationError("error must be an object or null")
        return cls(
            error_type=_string_or_default(
                data.get("type"),
                "error.type",
                "AgentError",
            ),
            message=_required_string(data, "message"),
        )


@dataclass(frozen=True)
class TelemetryEvent:
    event_id: str
    session_id: str
    conversation_id: str
    channel: str
    user_input: str
    output: str
    model: str
    provider_name: str
    endpoint: InferenceEndpoint
    caller: Caller
    usage: TokenUsage
    finish_reason: str | None
    error: ErrorDetails | None

    @classmethod
    def from_payload(cls, payload: object) -> TelemetryEvent:
        if not isinstance(payload, dict):
            raise ValidationError("request body must be a JSON object")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValidationError(f"schema_version must be '{SCHEMA_VERSION}'")

        output = payload.get("output", "")
        if not isinstance(output, str):
            raise ValidationError("output must be a string")
        return cls(
            event_id=_required_string(payload, "event_id"),
            session_id=_required_string(payload, "session_id"),
            conversation_id=_required_string(payload, "conversation_id"),
            channel=_string_or_default(
                payload.get("channel"),
                "channel",
                "console",
            ),
            user_input=_required_string(payload, "input"),
            output=output,
            model=_required_string(payload, "model"),
            provider_name=_required_string(payload, "provider_name"),
            endpoint=InferenceEndpoint.from_payload(
                payload.get("inference_endpoint")
            ),
            caller=Caller.from_payload(payload.get("caller")),
            usage=TokenUsage.from_payload(payload.get("usage")),
            finish_reason=_optional_string(
                payload.get("finish_reason"), "finish_reason"
            ),
            error=ErrorDetails.from_payload(payload.get("error")),
        )


def _required_string(data: dict[Any, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string")
    return value


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be a string or null")
    return value


def _string_or_default(value: object, name: str, default: str) -> str:
    if value is None or value == "":
        return default
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be a string")
    return value


def _optional_token_count(value: object, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError(
            f"{name} must be a non-negative integer or null"
        )
    return value
