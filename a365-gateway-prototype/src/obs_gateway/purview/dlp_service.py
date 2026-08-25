"""Apply Microsoft Purview DLP policy using protection scopes from Graph."""

from __future__ import annotations

import platform
import threading
import time
import uuid
from concurrent.futures import Future
from datetime import datetime, timezone
from typing import Protocol, cast
from urllib.parse import quote

from ..config import PurviewConfig
from ..shared.errors import GraphResponseError, PurviewDlpError
from .graph_client import PurviewGraphClient
from .types import (
    DOWNLOAD_TEXT,
    SUPPORTED_ACTIVITIES,
    UPLOAD_TEXT,
    DlpActivity,
    DlpDecision,
    DlpEvaluation,
    PolicyAction,
    ProtectionScopes,
)


class DlpEvaluator(Protocol):
    enabled: bool

    def evaluate(self, evaluation: DlpEvaluation) -> DlpDecision: ...


class DlpService:
    def __init__(
        self,
        config: PurviewConfig,
        graph: PurviewGraphClient,
    ) -> None:
        self._config = config
        self._graph = graph
        self.enabled = config.enabled
        self._scope_cache: dict[str, ProtectionScopes] = {}
        self._in_flight_scopes: dict[str, Future[ProtectionScopes]] = {}
        self._scope_lock = threading.Lock()

    def evaluate(self, evaluation: DlpEvaluation) -> DlpDecision:
        """Evaluate one activity and return the action its caller must enforce.

        Flow: load scopes, honor scope-level blocks, process in-scope content,
        and refresh once if Graph reports that the tenant policy changed.
        """

        if evaluation.activity not in SUPPORTED_ACTIVITIES:
            supported = ", ".join(sorted(SUPPORTED_ACTIVITIES))
            raise ValueError(f"activity must be one of: {supported}")
        if not self.enabled:
            return DlpDecision(
                allowed=True,
                activity=evaluation.activity,
                reason="Purview DLP is disabled",
            )

        try:
            scopes = self._get_protection_scopes(evaluation.user_id)
            actions = scopes.actions_for(evaluation.activity)
            if _contains_block_action(actions):
                return DlpDecision(
                    allowed=False,
                    activity=evaluation.activity,
                    policy_actions=actions,
                    reason="Purview protection scope requires blocking",
                )
            if not scopes.applies_to(evaluation.activity):
                return DlpDecision(
                    allowed=True,
                    activity=evaluation.activity,
                    reason="No Purview protection scope applies",
                )

            decision = self._process_content(evaluation, scopes)
            if decision.protection_scope_state == "modified":
                refreshed = self._get_protection_scopes(
                    evaluation.user_id, force=True
                )
                return self._process_content(evaluation, refreshed)
            return decision
        except Exception as exc:
            if self._config.fail_closed:
                if isinstance(exc, PurviewDlpError):
                    raise
                raise PurviewDlpError(
                    f"Purview DLP evaluation failed; activity blocked: {exc}"
                ) from exc
            return DlpDecision(
                allowed=True,
                activity=evaluation.activity,
                reason=f"Purview evaluation failed open: {exc}",
            )

    def _get_protection_scopes(
        self,
        user_id: str,
        *,
        force: bool = False,
    ) -> ProtectionScopes:
        now = time.monotonic()
        request_key = f"{user_id}:{'force' if force else 'normal'}"
        with self._scope_lock:
            cached = self._scope_cache.get(user_id)
            if not force and cached and cached.expires_at > now:
                return cached

            future = self._in_flight_scopes.get(request_key)
            owns_request = future is None
            if future is None:
                future = Future()
                self._in_flight_scopes[request_key] = future

        # Never hold the lock during network I/O. Other threads wait on the
        # Future created by the first cache miss for this user.
        if not owns_request:
            return future.result()

        try:
            scopes = self._compute_protection_scopes(user_id)
            with self._scope_lock:
                self._scope_cache[user_id] = scopes
            future.set_result(scopes)
            return scopes
        except BaseException as exc:
            future.set_exception(exc)
            raise
        finally:
            with self._scope_lock:
                self._in_flight_scopes.pop(request_key, None)

    def _compute_protection_scopes(self, user_id: str) -> ProtectionScopes:
        response = self._graph.post_json(
            operation="computeProtectionScopes",
            path=(
                f"/users/{quote(user_id, safe='')}/dataSecurityAndGovernance/"
                "protectionScopes/compute"
            ),
            body={
                "activities": f"{UPLOAD_TEXT},{DOWNLOAD_TEXT}",
                "locations": [
                    {
                        "@odata.type": (
                            "microsoft.graph.policyLocationApplication"
                        ),
                        "value": self._config.application_id,
                    }
                ],
                "integratedAppMetadata": self._app_metadata(),
            },
        )

        execution_modes: dict[DlpActivity, str] = {}
        actions_by_activity: dict[DlpActivity, list[PolicyAction]] = {}
        raw_scopes = response.body.get("value")
        if not isinstance(raw_scopes, list):
            raise GraphResponseError("computeProtectionScopes")
        for raw_scope in raw_scopes:
            if not isinstance(raw_scope, dict):
                raise GraphResponseError("computeProtectionScopes")
            mode = raw_scope.get("executionMode")
            activities = raw_scope.get("activities")
            if not isinstance(mode, str) or not isinstance(activities, str):
                raise GraphResponseError("computeProtectionScopes")
            actions = _parse_policy_actions(
                raw_scope.get("policyActions", []),
                "computeProtectionScopes",
            )
            for value in activities.split(","):
                activity_text = value.strip()
                if activity_text not in SUPPORTED_ACTIVITIES:
                    continue
                activity = cast(DlpActivity, activity_text)
                if mode == "evaluateInline" or activity not in execution_modes:
                    execution_modes[activity] = mode
                actions_by_activity.setdefault(activity, []).extend(actions)

        return ProtectionScopes(
            etag=response.headers.get("ETag") or response.headers.get("etag"),
            expires_at=time.monotonic() + self._config.scope_cache_seconds,
            execution_modes=execution_modes,
            policy_actions={
                activity: tuple(actions)
                for activity, actions in actions_by_activity.items()
            },
        )

    def _process_content(
        self,
        evaluation: DlpEvaluation,
        scopes: ProtectionScopes,
    ) -> DlpDecision:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        response = self._graph.post_json(
            operation="processContent",
            path=(
                f"/users/{quote(evaluation.user_id, safe='')}/"
                "dataSecurityAndGovernance/processContent"
            ),
            body={
                "contentToProcess": {
                    "contentEntries": [
                        {
                            "@odata.type": (
                                "microsoft.graph.processConversationMetadata"
                            ),
                            "identifier": str(uuid.uuid4()),
                            "content": {
                                "@odata.type": "microsoft.graph.textContent",
                                "data": evaluation.content,
                            },
                            "name": (
                                f"{self._config.app_name} "
                                f"{evaluation.activity}"
                            ),
                            "correlationId": evaluation.conversation_id,
                            "sequenceNumber": evaluation.sequence_number,
                            "isTruncated": False,
                            "createdDateTime": now,
                            "modifiedDateTime": now,
                        }
                    ],
                    "activityMetadata": {"activity": evaluation.activity},
                    "deviceMetadata": {
                        "deviceType": "Unmanaged",
                        "operatingSystemSpecifications": {
                            "operatingSystemPlatform": platform.system(),
                            "operatingSystemVersion": platform.release(),
                        },
                        "ipAddress": evaluation.client_ip,
                    },
                    "protectedAppMetadata": {
                        **self._app_metadata(),
                        "applicationLocation": {
                            "@odata.type": (
                                "microsoft.graph.policyLocationApplication"
                            ),
                            "value": self._config.application_id,
                        },
                    },
                    "integratedAppMetadata": self._app_metadata(),
                }
            },
            extra_headers=(
                {"If-None-Match": scopes.etag} if scopes.etag else None
            ),
        )

        mode = scopes.execution_modes.get(evaluation.activity)
        if response.status in {202, 204} and mode == "evaluateInline":
            raise PurviewDlpError(
                "Purview returned no inline policy decision; activity blocked"
            )

        actions = _parse_policy_actions(
            response.body.get("policyActions", []),
            "processContent",
        )
        blocked = _contains_block_action(actions)
        scope_state = response.body.get("protectionScopeState")
        if scope_state is not None and not isinstance(scope_state, str):
            raise GraphResponseError("processContent")
        return DlpDecision(
            allowed=not blocked,
            activity=evaluation.activity,
            policy_actions=actions,
            protection_scope_state=(
                scope_state if isinstance(scope_state, str) else None
            ),
            reason=(
                "Purview policy requires blocking"
                if blocked
                else "Purview policy evaluation allowed the activity"
            ),
        )

    def _app_metadata(self) -> dict[str, object]:
        return {
            "name": self._config.app_name,
            "version": self._config.app_version,
        }


def _contains_block_action(actions: tuple[PolicyAction, ...]) -> bool:
    return any(
        str(action.get("action", "")).lower() == "restrictaccess"
        and str(action.get("restrictionAction", "")).lower() == "block"
        for action in actions
    )


def _parse_policy_actions(
    value: object,
    operation: str,
) -> tuple[PolicyAction, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, dict) for item in value
    ):
        raise GraphResponseError(operation)
    return tuple(value)
