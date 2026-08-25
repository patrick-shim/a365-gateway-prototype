"""HTTP routing; feature modules own validation and business behavior."""

from __future__ import annotations

import logging
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from ..config import ServerConfig
from ..purview.dlp_service import DlpEvaluator
from ..purview.types import DlpEvaluation
from ..shared.errors import PurviewDlpError, ValidationError
from ..telemetry.event import TelemetryEvent
from ..telemetry.exporter import TelemetryExporter
from .request import is_authorized, read_json_body
from .response import send_json


LOGGER = logging.getLogger("obs_gateway.http")


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        config: ServerConfig,
        exporter: TelemetryExporter,
        dlp: DlpEvaluator,
    ) -> None:
        super().__init__(address, GatewayRequestHandler)
        self.config = config
        self.exporter = exporter
        self.dlp = dlp


class GatewayRequestHandler(BaseHTTPRequestHandler):
    server_version = "A365ObservabilityGateway/1.0"
    server: GatewayServer

    def do_GET(self) -> None:
        request_id, started_at = self._request_context()
        path = urlsplit(self.path).path
        if path == "/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "purview_dlp_enabled": self.server.dlp.enabled,
                },
                request_id,
            )
        else:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"error": "not found"},
                request_id,
            )
        self._log_completion(request_id, started_at)

    def do_POST(self) -> None:
        request_id, started_at = self._request_context()
        path = urlsplit(self.path).path
        if path not in {"/v1/telemetry", "/v1/dlp/evaluate"}:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"error": "not found"},
                request_id,
            )
            self._log_completion(request_id, started_at)
            return
        if not is_authorized(self, self.server.config.api_key):
            self._send_json(
                HTTPStatus.UNAUTHORIZED,
                {"error": "unauthorized"},
                request_id,
            )
            self._log_completion(request_id, started_at)
            return

        if path == "/v1/dlp/evaluate":
            self._handle_dlp(request_id)
        else:
            self._handle_telemetry(request_id)
        self._log_completion(request_id, started_at)

    def _handle_telemetry(self, request_id: str) -> None:
        try:
            payload = read_json_body(
                self, self.server.config.max_request_bytes
            )
            event = TelemetryEvent.from_payload(payload)
            event_id = self.server.exporter.export(event)
        except ValidationError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST, {"error": str(exc)}, request_id
            )
            return
        except Exception:
            LOGGER.exception(
                "Telemetry export failed request_id=%s", request_id
            )
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "telemetry export failed"},
                request_id,
            )
            return

        self._send_json(
            HTTPStatus.ACCEPTED,
            {"status": "exported", "event_id": event_id},
            request_id,
        )

    def _handle_dlp(self, request_id: str) -> None:
        try:
            payload = read_json_body(
                self, self.server.config.max_request_bytes
            )
            evaluation = DlpEvaluation.from_payload(payload)
            decision = self.server.dlp.evaluate(evaluation)
        except ValidationError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST, {"error": str(exc)}, request_id
            )
            return
        except PurviewDlpError as exc:
            # Content and tokens are deliberately omitted from operational logs.
            LOGGER.error(
                "Purview DLP evaluation failed request_id=%s error=%s",
                request_id,
                exc,
            )
            self._send_json(
                HTTPStatus.BAD_GATEWAY,
                {
                    "error": "Purview DLP evaluation failed; activity blocked",
                    "blocked": True,
                },
                request_id,
            )
            return
        except Exception:
            LOGGER.exception(
                "Unexpected Purview failure request_id=%s", request_id
            )
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": "internal gateway error; activity blocked",
                    "blocked": True,
                },
                request_id,
            )
            return

        self._send_json(HTTPStatus.OK, decision.as_dict(), request_id)

    def _send_json(
        self,
        status: int,
        payload: dict[str, object],
        request_id: str,
    ) -> None:
        send_json(self, status, payload, request_id=request_id)

    def _request_context(self) -> tuple[str, float]:
        request_id = self.headers.get("Client-Request-Id") or str(uuid.uuid4())
        return request_id, time.monotonic()

    def _log_completion(self, request_id: str, started_at: float) -> None:
        LOGGER.info(
            "request_id=%s method=%s path=%s duration_ms=%d",
            request_id,
            self.command,
            urlsplit(self.path).path,
            round((time.monotonic() - started_at) * 1000),
        )

    def log_message(self, format: str, *args: object) -> None:
        # Access logging is handled by _log_completion with a request ID.
        return


def create_gateway_server(
    *,
    config: ServerConfig,
    exporter: TelemetryExporter,
    dlp: DlpEvaluator,
) -> GatewayServer:
    return GatewayServer(
        (config.host, config.port),
        config=config,
        exporter=exporter,
        dlp=dlp,
    )
