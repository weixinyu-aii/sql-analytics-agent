from sql_agent.core.config import Settings
from sql_agent.llm.base import BaseLLM
from sql_agent.llm.mock import MockLLM
from sql_agent.llm.openai_compatible import OpenAICompatibleLLM


def create_llm(settings: Settings) -> BaseLLM:
    if settings.llm_provider == "mock":
        return MockLLM()
    return OpenAICompatibleLLM(
        provider_name=settings.llm_provider,
        base_url=settings.resolved_llm_base_url,
        model=settings.resolved_llm_model,
        api_key=settings.resolved_llm_api_key,
        timeout_seconds=settings.llm_timeout_seconds,
        temperature=settings.llm_temperature,
    )

