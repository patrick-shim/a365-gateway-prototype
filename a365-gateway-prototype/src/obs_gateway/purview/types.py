"""Validated request, decision, and cache types for Purview DLP."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypeAlias, cast

from ..shared.errors import ValidationError


UPLOAD_TEXT = "uploadText"
DOWNLOAD_TEXT = "downloadText"
SUPPORTED_ACTIVITIES = frozenset({UPLOAD_TEXT, DOWNLOAD_TEXT})

DlpActivity: TypeAlias = Literal["uploadText", "downloadText"]
PolicyAction: TypeAlias = dict[str, Any]


@dataclass(frozen=True)
class DlpEvaluation:
    user_id: str
    content: str
    activity: DlpActivity
    conversation_id: str
    sequence_number: int
    client_ip: str

    @classmethod
    def from_payload(cls, payload: object) -> DlpEvaluation:
        if not isinstance(payload, dict):
            raise ValidationError("request body must be a JSON object")

        sequence_number = payload.get("sequence_number")
        if (
            isinstance(sequence_number, bool)
            or not isinstance(sequence_number, int)
            or sequence_number < 0
        ):
            raise ValidationError(
                "sequence_number must be a non-negative integer"
            )

        activity = _required_string(payload, "activity")
        if activity not in SUPPORTED_ACTIVITIES:
            supported = ", ".join(sorted(SUPPORTED_ACTIVITIES))
            raise ValidationError(f"activity must be one of: {supported}")

        return cls(
            user_id=_required_string(payload, "user_id"),
            content=_required_string(payload, "content"),
            activity=cast(DlpActivity, activity),
            conversation_id=_required_string(payload, "conversation_id"),
            sequence_number=sequence_number,
            client_ip=_string_or_default(
                payload.get("client_ip"),
                "client_ip",
                "127.0.0.1",
            ),
        )


@dataclass(frozen=True)
class DlpDecision:
    allowed: bool
    activity: DlpActivity
    policy_actions: tuple[PolicyAction, ...] = ()
    protection_scope_state: str | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "blocked": not self.allowed,
            "activity": self.activity,
            "policy_actions": list(self.policy_actions),
            "protection_scope_state": self.protection_scope_state,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ProtectionScopes:
    etag: str | None
    expires_at: float
    execution_modes: dict[DlpActivity, str]
    policy_actions: dict[DlpActivity, tuple[PolicyAction, ...]]

    def actions_for(self, activity: DlpActivity) -> tuple[PolicyAction, ...]:
        return self.policy_actions.get(activity, ())

    def applies_to(self, activity: DlpActivity) -> bool:
        return activity in self.execution_modes


def _required_string(data: dict[object, object], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string")
    return value


def _string_or_default(value: object, name: str, default: str) -> str:
    if value is None or value == "":
        return default
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be a string")
    return value
