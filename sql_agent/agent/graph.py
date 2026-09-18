from __future__ import annotations

import time
import uuid

from sql_agent.agent.intent import IntentClassifier
from sql_agent.agent.nodes import (
    IntentNode,
    SchemaRetrievalNode,
    SQLExecutionNode,
    SQLGenerationNode,
    SQLValidationNode,
    SummaryNode,
    VisualizationNode,
)
from sql_agent.agent.schema_catalog import SchemaCatalog
from sql_agent.agent.state import AgentResult, AgentState, TraceStep
from sql_agent.core.exceptions import AgentQueryError, LLMProviderError
from sql_agent.llm.base import BaseLLM
from sql_agent.security.sql_guard import SQLGuard
from sql_agent.services.executor import ReadOnlyQueryExecutor
from sql_agent.services.visualization import VisualizationSelector


class AnalyticsAgent:
    """A transparent state-machine implementation of the Text2SQL workflow."""

    def __init__(
        self,
        *,
        catalog: SchemaCatalog,
        llm: BaseLLM,
        guard: SQLGuard,
        executor: ReadOnlyQueryExecutor,
        dialect: str,
        max_rows: int = 200,
        max_retries: int = 2,
    ) -> None:
        self.llm = llm
        self.max_rows = max_rows
        self.max_retries = max_retries
        self.dialect = dialect
        self.intent_node = IntentNode(IntentClassifier())
        self.schema_node = SchemaRetrievalNode(catalog, dialect)
        self.generation_node = SQLGenerationNode(llm, dialect, max_rows)
        self.validation_node = SQLValidationNode(guard, dialect)
        self.execution_node = SQLExecutionNode(executor)
        self.visualization_node = VisualizationNode(VisualizationSelector())
        self.summary_node = SummaryNode(llm)

    async def run(self, question: str) -> AgentResult:
        started = time.perf_counter()
        state = AgentState(
            request_id=str(uuid.uuid4()),
            question=question.strip(),
        )

        self.intent_node.run(state)
        self.schema_node.run(state)

        executed = False
        last_error: str | None = None
        for _ in range(self.max_retries + 1):
            try:
                await self.generation_node.run(state)
            except LLMProviderError as exc:
                last_error = exc.message
                state.previous_error = exc.message
                if state.attempts > self.max_retries:
                    break
                continue

            if not self.validation_node.run(state):
                last_error = state.previous_error
                if state.attempts > self.max_retries:
                    break
                continue

            if await self.execution_node.run(state):
                executed = True
                break

            last_error = state.previous_error
            if state.attempts > self.max_retries:
                break

        if not executed:
            raise AgentQueryError(
                f"SQL 在 {self.max_retries + 1} 次尝试后仍未成功。",
                detail={"last_error": last_error, "trace": [item.model_dump() for item in state.trace]},
            )

        self.visualization_node.run(state)
        await self.summary_node.run(state)
        state.trace.append(
            TraceStep(
                step="pipeline_complete",
                duration_ms=int((time.perf_counter() - started) * 1_000),
                detail=f"Agent 流程完成，共尝试 {state.attempts} 次。",
            )
        )
        return AgentResult(
            **state.model_dump(),
            llm_provider=self.llm.provider_name,
        )

