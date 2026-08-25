"""HTTP client for Purview DLP decisions and Agent 365 telemetry."""

from __future__ import annotations

import json
import math
import os
import socket
import sys
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from azure.core.credentials import TokenCredential
from openai.types.chat import ChatCompletion

from .config import (
    TELEMETRY_SCHEMA_VERSION,
    AgentSettings,
    env_is_true,
    required_env,
)
from .models import Caller, ConversationContext, DlpDecision


class TelemetryClient:
    """Build and POST inference events without importing the Agent 365 SDK."""

    def __init__(
        self,
        *,
        gateway_url: str,
        dlp_url: str,
        model: str,
        inference_endpoint: str,
        caller: Caller,
        channel: str,
        timeout_seconds: float,
        delivery_required: bool,
        api_key: str | None,
    ) -> None:
        self.gateway_url = gateway_url
        self.dlp_url = dlp_url
        self.model = model
        self.caller = caller
        self.channel = channel
        self.timeout_seconds = timeout_seconds
        self.delivery_required = delivery_required
        self.api_key = api_key

        parsed_endpoint = urlparse(inference_endpoint)
        self.inference_hostname = parsed_endpoint.hostname or socket.gethostname()
        self.inference_port = parsed_endpoint.port or 443

    @classmethod
    def from_environment(
        cls,
        *,
        credential: TokenCredential,
        settings: AgentSettings,
    ) -> TelemetryClient:
        gateway_url = required_env("OBS_GATEWAY_URL")
        timeout_text = os.getenv("OBS_GATEWAY_TIMEOUT_SECONDS", "10")
        try:
            timeout_seconds = float(timeout_text)
        except ValueError as exc:
            raise RuntimeError(
                "OBS_GATEWAY_TIMEOUT_SECONDS must be a positive finite number"
            ) from exc
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise RuntimeError(
                "OBS_GATEWAY_TIMEOUT_SECONDS must be a positive finite number"
            )

        return cls(
            gateway_url=gateway_url,
            dlp_url=os.getenv("OBS_GATEWAY_DLP_URL")
            or f"{gateway_url.rsplit('/', 1)[0]}/dlp/evaluate",
            model=settings.deployment,
            inference_endpoint=settings.endpoint,
            caller=Caller.from_azure_credential(credential, settings.scope),
            channel=os.getenv("TELEMETRY_CHANNEL", "console"),
            timeout_seconds=timeout_seconds,
            delivery_required=env_is_true("OBS_GATEWAY_REQUIRED", True),
            api_key=os.getenv("OBS_GATEWAY_API_KEY") or None,
        )

    def evaluate_content(
        self,
        *,
        content: str,
        activity: str,
        context: ConversationContext,
        sequence_number: int,
    ) -> DlpDecision:
        """Ask the gateway to enforce Purview policy before content proceeds."""

        if not content:
            return DlpDecision(allowed=True, reason="Content is empty")
        response = self._post_json(
            self.dlp_url,
            {
                "user_id": self.caller.user_id,
                "content": content,
                "activity": activity,
                "conversation_id": context.conversation_id,
                "sequence_number": sequence_number,
                "client_ip": self.caller.client_ip,
            },
        )
        allowed = response.get("allowed")
        if not isinstance(allowed, bool):
            raise RuntimeError("gateway returned an invalid DLP decision")
        reason = response.get("reason")
        return DlpDecision(
            allowed=allowed,
            reason=reason if isinstance(reason, str) else None,
        )

    def record_completion(
        self,
        *,
        user_input: str,
        answer: str,
        response: ChatCompletion,
        context: ConversationContext,
    ) -> bool:
        """Report a successful model call and return whether delivery succeeded."""

        usage = response.usage
        return self._send(
            self._build_event(
                user_input=user_input,
                answer=answer,
                context=context,
                input_tokens=usage.prompt_tokens if usage else None,
                output_tokens=usage.completion_tokens if usage else None,
                finish_reason=response.choices[0].finish_reason,
            )
        )

    def record_failure(
        self,
        *,
        user_input: str,
        error: Exception,
        context: ConversationContext,
    ) -> bool:
        """Report a failed model call and return whether delivery succeeded."""

        return self._send(
            self._build_event(
                user_input=user_input,
                answer="",
                context=context,
                error=error,
            )
        )

    def _build_event(
        self,
        *,
        user_input: str,
        answer: str,
        context: ConversationContext,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        finish_reason: str | None = None,
        error: Exception | None = None,
    ) -> dict[str, object]:
        event: dict[str, object] = {
            "schema_version": TELEMETRY_SCHEMA_VERSION,
            "event_id": str(uuid.uuid4()),
            "session_id": context.session_id,
            "conversation_id": context.conversation_id,
            "channel": self.channel,
            "input": user_input,
            "output": answer,
            "model": self.model,
            "provider_name": "azure-openai",
            "inference_endpoint": {
                "hostname": self.inference_hostname,
                "port": self.inference_port,
            },
            "caller": {
                "id": self.caller.user_id,
                "email": self.caller.email,
                "name": self.caller.name,
                "client_ip": self.caller.client_ip,
            },
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
            "finish_reason": finish_reason,
        }
        if error is not None:
            event["error"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
        return event

    def _send(self, event: dict[str, object]) -> bool:
        try:
            self._post_json(self.gateway_url, event)
            return True
        except Exception as exc:
            if self.delivery_required:
                raise RuntimeError(f"telemetry delivery failed: {exc}") from exc
            print(f"Telemetry warning: {exc}", file=sys.stderr)
            return False

    def _post_json(
        self,
        url: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                if response.status not in {200, 202}:
                    raise RuntimeError(f"gateway returned HTTP {response.status}")
                raw_body = response.read()
                if not raw_body:
                    return {}
                parsed = json.loads(raw_body)
                if not isinstance(parsed, dict):
                    raise RuntimeError("gateway returned an invalid JSON response")
                return parsed
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"gateway returned HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"cannot reach gateway: {exc.reason}") from exc
