"""Assemble and run the gateway's HTTP, DLP, and telemetry components."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .auth.token_provider import create_token_provider
from .config import GatewayConfig
from .http.server import GatewayServer, create_gateway_server
from .purview.dlp_service import DlpService
from .purview.graph_client import PurviewGraphClient
from .telemetry.exporter import (
    TelemetryExporter,
    create_telemetry_exporter,
)


LOGGER = logging.getLogger("obs_gateway")


@dataclass(frozen=True)
class GatewayRuntime:
    """Live resources that must be shut down together."""

    server: GatewayServer
    exporter: TelemetryExporter


def build_runtime(config: GatewayConfig) -> GatewayRuntime:
    """Create the gateway dependency graph from validated configuration."""

    tokens = create_token_provider(config.agent)
    graph = PurviewGraphClient(
        config.purview,
        tokens.get_graph_access_token,
    )
    dlp = DlpService(config.purview, graph)
    exporter = create_telemetry_exporter(config.observability, tokens)
    try:
        server = create_gateway_server(
            config=config.server,
            exporter=exporter,
            dlp=dlp,
        )
    except Exception:
        exporter.shutdown()
        raise
    return GatewayRuntime(server=server, exporter=exporter)


def serve(runtime: GatewayRuntime, config: GatewayConfig) -> None:
    """Serve until interrupted, then release HTTP and telemetry resources."""

    LOGGER.info(
        "Agent 365 observability gateway listening on http://%s:%d",
        config.server.host,
        runtime.server.server_address[1],
    )
    LOGGER.info("Purview DLP enabled: %s", config.purview.enabled)
    LOGGER.info("DLP endpoint: POST /v1/dlp/evaluate")
    LOGGER.info("Telemetry endpoint: POST /v1/telemetry")
    try:
        runtime.server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Shutdown requested")
    finally:
        runtime.server.server_close()
        runtime.exporter.shutdown()
