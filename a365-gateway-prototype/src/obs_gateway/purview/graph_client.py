"""Authenticated JSON transport for the Microsoft Graph Purview endpoints."""

from __future__ import annotations

import json
import socket
import ssl
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import truststore

from ..config import PurviewConfig
from ..shared.errors import (
    GraphHttpError,
    GraphResponseError,
    GraphTimeoutError,
    PurviewDlpError,
)


@dataclass(frozen=True)
class GraphResponse:
    body: dict[str, Any]
    headers: Mapping[str, str]
    status: int


GraphTransport = Callable[
    [Request, float], tuple[bytes, Mapping[str, str], int]
]


# Python.org builds on macOS do not automatically use certificates installed in
# Keychain.  Truststore keeps verification enabled while using the operating
# system trust store (and therefore also supports managed/corporate roots).
_SSL_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


class PurviewGraphClient:
    def __init__(
        self,
        config: PurviewConfig,
        token_provider: Callable[[], str],
        *,
        transport: GraphTransport | None = None,
    ) -> None:
        self._config = config
        self._token_provider = token_provider
        self._transport = transport or _urlopen_transport

    def post_json(
        self,
        *,
        operation: str,
        path: str,
        body: Mapping[str, object],
        extra_headers: Mapping[str, str] | None = None,
    ) -> GraphResponse:
        headers = {
            "Authorization": f"Bearer {self._token_provider()}",
            "Content-Type": "application/json",
            "Client-Request-Id": str(uuid.uuid4()),
        }
        if extra_headers:
            headers.update(extra_headers)
        request = Request(
            f"{self._config.graph_base_url}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            raw_body, response_headers, status = self._transport(
                request, self._config.request_timeout_seconds
            )
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GraphHttpError(operation, exc.code, detail) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise GraphTimeoutError(
                operation, self._config.request_timeout_seconds
            ) from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise GraphTimeoutError(
                    operation, self._config.request_timeout_seconds
                ) from exc
            raise PurviewDlpError(
                f"Cannot reach Microsoft Graph during {operation}: {exc.reason}"
            ) from exc
        except PurviewDlpError:
            raise
        except OSError as exc:
            raise PurviewDlpError(
                f"Cannot reach Microsoft Graph during {operation}: {exc}"
            ) from exc

        if not 200 <= status < 300:
            detail = raw_body.decode("utf-8", errors="replace")
            raise GraphHttpError(operation, status, detail)

        try:
            parsed = json.loads(raw_body) if raw_body else {}
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise GraphResponseError(operation) from exc
        if not isinstance(parsed, dict):
            raise GraphResponseError(operation)
        return GraphResponse(parsed, response_headers, status)


def _urlopen_transport(
    request: Request,
    timeout_seconds: float,
) -> tuple[bytes, Mapping[str, str], int]:
    with urlopen(
        request,
        timeout=timeout_seconds,
        context=_SSL_CONTEXT,
    ) as response:
        return response.read(), response.headers, response.status
