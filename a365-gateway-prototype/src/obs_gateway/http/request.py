"""Read and authenticate gateway HTTP requests."""

from __future__ import annotations

import hmac
import json
from http.server import BaseHTTPRequestHandler

from ..shared.errors import ValidationError


def read_json_body(
    handler: BaseHTTPRequestHandler,
    max_request_bytes: int,
) -> object:
    if handler.headers.get_content_type() != "application/json":
        raise ValidationError("Content-Type must be application/json")
    try:
        content_length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise ValidationError("invalid Content-Length") from exc
    if not 0 < content_length <= max_request_bytes:
        raise ValidationError(
            f"request body must be between 1 and {max_request_bytes} bytes"
        )

    try:
        return json.loads(handler.rfile.read(content_length))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValidationError(
            "request body must contain valid JSON"
        ) from exc


def is_authorized(
    handler: BaseHTTPRequestHandler,
    expected_api_key: str | None,
) -> bool:
    if not expected_api_key:
        return True
    supplied = handler.headers.get("Authorization", "")
    return hmac.compare_digest(supplied, f"Bearer {expected_api_key}")
