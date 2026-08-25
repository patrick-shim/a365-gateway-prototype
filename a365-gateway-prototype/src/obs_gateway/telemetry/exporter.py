"""Convert validated events into Agent 365 OpenTelemetry spans."""

from __future__ import annotations

import logging
from typing import Protocol

from microsoft.opentelemetry import use_microsoft_opentelemetry
from microsoft.opentelemetry.a365.core import (
    AgentDetails,
    BaggageBuilder,
    CallerDetails,
    Channel,
    InferenceCallDetails,
    InferenceOperationType,
    InferenceScope,
    InvokeAgentScope,
    InvokeAgentScopeDetails,
    Request,
    ServiceEndpoint,
    UserDetails,
)
from opentelemetry import trace

from ..auth.token_provider import AgentTokenProvider
from ..config import ObservabilityConfig
from .event import TelemetryEvent


class TelemetryExporter(Protocol):
    def export(self, event: TelemetryEvent) -> str: ...

    def flush(self) -> None: ...

    def shutdown(self) -> None: ...


def create_telemetry_exporter(
    config: ObservabilityConfig,
    tokens: AgentTokenProvider,
) -> TelemetryExporter:
    agent_details = AgentDetails(
        agent_id=config.agent.agent_id,
        agent_name=config.agent.agent_name,
        agent_description=config.agent.agent_description,
        agent_blueprint_id=config.agent.agent_blueprint_id,
        tenant_id=config.agent.tenant_id,
    )
    exporter = Agent365TelemetryExporter(config, tokens, agent_details)
    if config.remote_export_enabled:
        # The background exporter uses a synchronous token resolver, so its
        # cache must contain a token before telemetry can be emitted.
        tokens.refresh_observability_token()
    exporter.configure_opentelemetry()
    return exporter


class Agent365TelemetryExporter:
    def __init__(
        self,
        config: ObservabilityConfig,
        tokens: AgentTokenProvider,
        agent_details: AgentDetails,
    ) -> None:
        self._config = config
        self._tokens = tokens
        self._agent_details = agent_details

    def configure_opentelemetry(self) -> None:
        log_level = getattr(logging, self._config.log_level, logging.INFO)
        logging.getLogger(
            "microsoft.opentelemetry.a365.core.exporters.agent365_exporter"
        ).setLevel(log_level)
        logging.getLogger(
            "microsoft.opentelemetry.a365.core.exporters.utils"
        ).setLevel(log_level)

        use_microsoft_opentelemetry(
            enable_a365=self._config.enabled,
            enable_console=self._config.console_enabled,
            a365_token_resolver=self._tokens.resolve_observability_token,
            a365_use_s2s_endpoint=self._config.use_s2s_endpoint,
            a365_enable_observability_exporter=(
                self._config.remote_export_enabled
            ),
            a365_scheduled_delay_ms=1000,
            instrumentation_options={
                # The gateway receives completed calls. It does not make the
                # OpenAI request, so automatic OpenAI instrumentation stays off.
                "openai": {"enabled": False},
                "openai_agents": {"enabled": False},
            },
        )

    def export(self, event: TelemetryEvent) -> str:
        if self._config.remote_export_enabled:
            self._tokens.refresh_observability_token()

        user_details = UserDetails(
            user_id=event.caller.user_id,
            user_email=event.caller.email,
            user_name=event.caller.name,
            user_client_ip=event.caller.client_ip,
        )
        endpoint = ServiceEndpoint(
            hostname=event.endpoint.hostname,
            port=event.endpoint.port,
        )
        request = Request(
            content=event.user_input,
            session_id=event.session_id,
            conversation_id=event.conversation_id,
            channel=Channel(name=event.channel),
        )
        inference_details = InferenceCallDetails(
            operationName=InferenceOperationType.CHAT,
            model=event.model,
            providerName=event.provider_name,
            endpoint=endpoint,
        )
        recorded_error = self._as_exception(event)
        baggage = self._build_baggage(event, endpoint)

        # The outer span represents the agent turn. The nested span represents
        # the model inference that produced the response.
        with baggage:
            with InvokeAgentScope.start(
                request=request,
                scope_details=InvokeAgentScopeDetails(endpoint=endpoint),
                agent_details=self._agent_details,
                caller_details=CallerDetails(user_details=user_details),
            ) as invoke_scope:
                invoke_scope.record_input_messages([event.user_input])
                with InferenceScope.start(
                    request=request,
                    details=inference_details,
                    agent_details=self._agent_details,
                    user_details=user_details,
                ) as inference_scope:
                    self._record_inference(
                        event, inference_scope, recorded_error
                    )

                if event.output:
                    invoke_scope.record_output_messages([event.output])
                if recorded_error:
                    invoke_scope.record_error(recorded_error)

        # Return 202 only after the provider accepts the completed spans.
        self.flush()
        return event.event_id

    def flush(self) -> None:
        provider = trace.get_tracer_provider()
        force_flush = getattr(provider, "force_flush", None)
        if callable(force_flush):
            force_flush(timeout_millis=30_000)

    def shutdown(self) -> None:
        self.flush()
        provider = trace.get_tracer_provider()
        shutdown = getattr(provider, "shutdown", None)
        if callable(shutdown):
            shutdown()

    def _build_baggage(
        self,
        event: TelemetryEvent,
        endpoint: ServiceEndpoint,
    ):
        return (
            BaggageBuilder()
            .tenant_id(self._agent_details.tenant_id)
            .agent_id(self._agent_details.agent_id)
            .agent_name(self._agent_details.agent_name)
            .agent_description(self._agent_details.agent_description)
            .agent_blueprint_id(self._agent_details.agent_blueprint_id)
            .conversation_id(event.conversation_id)
            .session_id(event.session_id)
            .channel_name(event.channel)
            .user_id(event.caller.user_id)
            .user_email(event.caller.email)
            .user_name(event.caller.name)
            .user_client_ip(event.caller.client_ip)
            .invoke_agent_server(endpoint.hostname, endpoint.port)
            .build()
        )

    @staticmethod
    def _record_inference(event, scope, recorded_error) -> None:
        scope.record_input_messages([event.user_input])
        if event.output:
            scope.record_output_messages([event.output])
        if event.usage.input_tokens is not None:
            scope.record_input_tokens(event.usage.input_tokens)
        if event.usage.output_tokens is not None:
            scope.record_output_tokens(event.usage.output_tokens)
        if event.finish_reason:
            scope.record_finish_reasons([event.finish_reason])
        if recorded_error:
            scope.record_error(recorded_error)

    @staticmethod
    def _as_exception(event: TelemetryEvent) -> RuntimeError | None:
        if event.error is None:
            return None
        return RuntimeError(
            f"{event.error.error_type}: {event.error.message}"
        )
