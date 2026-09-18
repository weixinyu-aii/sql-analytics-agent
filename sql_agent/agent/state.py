from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from sql_agent.security.sql_guard import SQLSafetyResult
from sql_agent.services.visualization import ChartSpec


class TraceStep(BaseModel):
    step: str
    status: str = "completed"
    duration_ms: int = 0
    detail: str = ""


class AgentState(BaseModel):
    request_id: str
    question: str
    intent: str = "analytics"
    intent_confidence: float = 0.0
    matched_keywords: list[str] = Field(default_factory=list)
    relevant_tables: list[str] = Field(default_factory=list)
    schema_context: str = ""
    sql: str = ""
    original_sql: str = ""
    sql_explanation: str = ""
    assumptions: list[str] = Field(default_factory=list)
    safety: SQLSafetyResult | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    execution_ms: int = 0
    attempts: int = 0
    previous_error: str | None = None
    chart: ChartSpec = Field(default_factory=ChartSpec)
    summary: str = ""
    highlights: list[str] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentResult(AgentState):
    llm_provider: str

