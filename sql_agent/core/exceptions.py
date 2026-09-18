class AppError(Exception):
    """Base class for expected application errors."""

    code = "app_error"

    def __init__(self, message: str, *, detail: object | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class SQLSafetyError(AppError):
    code = "unsafe_sql"


class SQLExecutionError(AppError):
    code = "sql_execution_error"


class AgentQueryError(AppError):
    code = "agent_query_error"


class LLMProviderError(AppError):
    code = "llm_provider_error"

