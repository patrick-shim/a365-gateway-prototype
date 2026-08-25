"""Environment-backed configuration for the Agent 365 gateway test agent."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_SIT_FILE = PROJECT_ROOT / "sits.yaml"
TELEMETRY_SCHEMA_VERSION = "1.0"


def required_env(name: str) -> str:
    """Return a required, non-empty environment variable."""

    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def env_is_true(name: str, default: bool) -> bool:
    """Parse the agent's permissive true-value environment convention."""

    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AgentSettings:
    """Azure OpenAI settings owned by this application."""

    endpoint: str
    deployment: str
    api_version: str
    scope: str
    system_prompt: str

    @classmethod
    def from_environment(cls, env_file: Path | None = None) -> AgentSettings:
        """Load settings from the agent-local ``.env`` and process environment."""

        path = env_file or ENV_FILE
        if not path.is_file():
            raise RuntimeError(f"Environment file not found: {path}")
        load_dotenv(dotenv_path=path)
        return cls(
            endpoint=required_env("AZURE_OPENAI_ENDPOINT"),
            deployment=required_env("AZURE_OPENAI_DEPLOYMENT"),
            api_version=required_env("AZURE_OPENAI_API_VERSION"),
            scope=required_env("AZURE_OPENAI_SCOPE"),
            system_prompt=required_env("AZURE_OPENAI_SYSTEM_PROMPT"),
        )
