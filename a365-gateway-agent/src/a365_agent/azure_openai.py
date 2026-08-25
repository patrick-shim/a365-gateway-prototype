"""Azure OpenAI client construction."""

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

from .config import AgentSettings


def build_openai_client(
    settings: AgentSettings,
    credential: DefaultAzureCredential,
) -> AzureOpenAI:
    """Create an Azure OpenAI client backed by Microsoft Entra tokens."""

    token_provider = get_bearer_token_provider(credential, settings.scope)
    return AzureOpenAI(
        api_version=settings.api_version,
        azure_endpoint=settings.endpoint,
        azure_ad_token_provider=token_provider,
    )
