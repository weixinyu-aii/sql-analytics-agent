from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class SQLGeneration(BaseModel):
    sql: str
    explanation: str = ""
    tables_used: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class ResultSummary(BaseModel):
    summary: str
    highlights: list[str] = Field(default_factory=list)


class BaseLLM(ABC):
    provider_name = "base"

    @abstractmethod
    async def generate_sql(
        self,
        *,
        question: str,
        intent: str,
        schema_context: str,
        dialect: str,
        max_rows: int,
        previous_error: str | None = None,
    ) -> SQLGeneration:
        raise NotImplementedError

    @abstractmethod
    async def summarize_result(
        self,
        *,
        question: str,
        intent: str,
        columns: list[str],
        rows: list[list[object]],
        truncated: bool,
    ) -> ResultSummary:
        raise NotImplementedError

