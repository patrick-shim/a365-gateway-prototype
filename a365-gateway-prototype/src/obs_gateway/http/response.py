"""Write JSON gateway responses consistently."""

from __future__ import annotations

import json
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler


def send_json(
    handler: BaseHTTPRequestHandler,
    status: int,
    payload: Mapping[str, object],
    *,
    request_id: str,
) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Client-Request-Id", request_id)
    handler.end_headers()
    handler.wfile.write(body)
