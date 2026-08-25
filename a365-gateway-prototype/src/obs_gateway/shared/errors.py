"""Errors that cross feature boundaries inside the gateway."""

from __future__ import annotations


class ConfigurationError(RuntimeError):
    """Raised when startup configuration is missing or invalid."""


class ValidationError(ValueError):
    """Raised when an HTTP payload does not match the public contract."""


class PurviewDlpError(RuntimeError):
    """Raised when policy evaluation cannot be completed safely."""


class GraphTimeoutError(PurviewDlpError):
    def __init__(self, operation: str, timeout_seconds: float) -> None:
        super().__init__(
            f"Microsoft Graph {operation} timed out after "
            f"{timeout_seconds:g} seconds"
        )
        self.operation = operation
        self.timeout_seconds = timeout_seconds


class GraphHttpError(PurviewDlpError):
    def __init__(self, operation: str, status: int, response_body: str) -> None:
        super().__init__(
            f"Microsoft Graph {operation} returned HTTP {status}: {response_body}"
        )
        self.operation = operation
        self.status = status
        self.response_body = response_body


class GraphResponseError(PurviewDlpError):
    def __init__(self, operation: str) -> None:
        super().__init__(
            f"Microsoft Graph {operation} returned an unexpected response"
        )
        self.operation = operation
