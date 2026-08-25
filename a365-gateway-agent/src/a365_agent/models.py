"""Shared immutable values passed between agent components."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

from azure.core.credentials import TokenCredential
from jwt import decode as decode_jwt


@dataclass(frozen=True)
class ConversationContext:
    """Identifiers used to group turns in the Agent 365 activity view."""

    session_id: str
    conversation_id: str

    @classmethod
    def new(cls) -> ConversationContext:
        return cls(
            session_id=str(uuid.uuid4()),
            conversation_id=str(uuid.uuid4()),
        )


@dataclass(frozen=True)
class Caller:
    """End-user information attached to DLP and telemetry requests."""

    user_id: str
    email: str | None
    name: str | None
    client_ip: str

    @classmethod
    def from_azure_credential(
        cls,
        credential: TokenCredential,
        azure_openai_scope: str,
    ) -> Caller:
        """Derive caller metadata from a token without forwarding the token."""

        access_token = credential.get_token(azure_openai_scope).token
        claims = decode_jwt(
            access_token,
            options={"verify_signature": False, "verify_aud": False},
        )
        user_id = os.getenv("CALLER_USER_ID") or claims.get("oid")
        if not user_id:
            raise RuntimeError(
                "Set CALLER_USER_ID because the Azure credential has no user object ID"
            )
        return cls(
            user_id=user_id,
            email=os.getenv("CALLER_USER_EMAIL")
            or claims.get("preferred_username")
            or claims.get("upn"),
            name=os.getenv("CALLER_USER_NAME") or claims.get("name"),
            client_ip=os.getenv("CALLER_CLIENT_IP", "127.0.0.1"),
        )


@dataclass(frozen=True)
class DlpDecision:
    """Purview's allow/block decision returned by the gateway."""

    allowed: bool
    reason: str | None


@dataclass(frozen=True)
class SitSample:
    """One synthetic content sample and its expected Purview action."""

    sample_id: str
    sit_type: str
    content: str
    expected_action: str
