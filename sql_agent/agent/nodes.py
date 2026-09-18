from __future__ import annotations

import time

from sql_agent.agent.intent import IntentClassifier
from sql_agent.agent.schema_catalog import SchemaCatalog
from sql_agent.agent.state import AgentState, TraceStep
from sql_agent.core.exceptions import SQLSafetyError
from sql_agent.llm.base import BaseLLM
from sql_agent.security.sql_guard import SQLGuard
from sql_agent.services.executor import ReadOnlyQueryExecutor
from sql_agent.services.visualization import VisualizationSelector


def _trace(
    state: AgentState,
    step: str,
    *,
    duration_ms: int,
    status: str = "completed",
    detail: str = "",
) -> None:
    state.trace.append(
        TraceStep(
            step=step,
            status=status,
            duration_ms=duration_ms,
            detail=detail,
        )
    )


class IntentNode:
    def __init__(self, classifier: IntentClassifier) -> None:
        self.classifier = classifier

    def run(self, state: AgentState) -> AgentState:
        started = time.perf_counter()
        result = self.classifier.classify(state.question)
        state.intent = result.intent.value
        state.intent_confidence = result.confidence
        state.matched_keywords = result.matched_keywords
        _trace(
            state,
            "intent_recognition",
            duration_ms=int((time.perf_counter() - started) * 1_000),
            detail=f"识别为 {state.intent}，置信度 {state.intent_confidence:.2f}",
        )
        return state


class SchemaRetrievalNode:
    def __init__(self, catalog: SchemaCatalog, dialect: str) -> None:
        self.catalog = catalog
        self.dialect = dialect

    def run(self, state: AgentState) -> AgentState:
        started = time.perf_counter()
        retrieval = self.catalog.retrieve(state.question, intent=state.intent)
        state.relevant_tables = retrieval.table_names
        state.schema_context = self.catalog.to_prompt(retrieval, self.dialect)
        _trace(
            state,
            "schema_retrieval",
            duration_ms=int((time.perf_counter() - started) * 1_000),
            detail=f"检索到相关表：{', '.join(state.relevant_tables)}",
        )
        return state


class SQLGenerationNode:
    def __init__(self, llm: BaseLLM, dialect: str, max_rows: int) -> None:
        self.llm = llm
        self.dialect = dialect
        self.max_rows = max_rows

    async def run(self, state: AgentState) -> AgentState:
        started = time.perf_counter()
        state.attempts += 1
        generation = await self.llm.generate_sql(
            question=state.question,
            intent=state.intent,
            schema_context=state.schema_context,
            dialect=self.dialect,
            max_rows=self.max_rows,
            previous_error=state.previous_error,
        )
        state.original_sql = generation.sql
        state.sql = generation.sql
        state.sql_explanation = generation.explanation
        state.assumptions = generation.assumptions
        state.previous_error = None
        _trace(
            state,
            "sql_generation",
            duration_ms=int((time.perf_counter() - started) * 1_000),
            status="retry" if state.attempts > 1 else "completed",
            detail=f"第 {state.attempts} 次生成 SQL。",
        )
        return state


class SQLValidationNode:
    def __init__(self, guard: SQLGuard, dialect: str) -> None:
        self.guard = guard
        self.dialect = dialect

    def run(self, state: AgentState) -> bool:
        started = time.perf_counter()
        try:
            safety = self.guard.validate(state.sql, dialect=self.dialect)
            state.sql = safety.sql
            state.safety = safety
            _trace(
                state,
                "sql_safety_validation",
                duration_ms=int((time.perf_counter() - started) * 1_000),
                detail=(
                    f"校验通过，访问表：{', '.join(safety.tables) or '无'}；"
                    f"强制 LIMIT {safety.applied_limit}"
                ),
            )
            return True
        except SQLSafetyError as exc:
            state.previous_error = exc.message
            _trace(
                state,
                "sql_safety_validation",
                duration_ms=int((time.perf_counter() - started) * 1_000),
                status="failed",
                detail=exc.message,
            )
            return False


class SQLExecutionNode:
    def __init__(self, executor: ReadOnlyQueryExecutor) -> None:
        self.executor = executor

    async def run(self, state: AgentState) -> bool:
        started = time.perf_counter()
        try:
            result = await self.executor.execute(state.sql)
            state.columns = result.columns
            state.rows = result.rows
            state.row_count = result.row_count
            state.truncated = result.truncated
            state.execution_ms = result.execution_ms
            _trace(
                state,
                "readonly_execution",
                duration_ms=int((time.perf_counter() - started) * 1_000),
                detail=f"返回 {result.row_count} 行，耗时 {result.execution_ms} ms。",
            )
            return True
        except Exception as exc:
            state.previous_error = str(exc)
            _trace(
                state,
                "readonly_execution",
                duration_ms=int((time.perf_counter() - started) * 1_000),
                status="failed",
                detail=str(exc),
            )
            return False


class VisualizationNode:
    def __init__(self, selector: VisualizationSelector) -> None:
        self.selector = selector

    def run(self, state: AgentState) -> AgentState:
        started = time.perf_counter()
        state.chart = self.selector.select(
            columns=state.columns,
            rows=state.rows,
            intent=state.intent,
            question=state.question,
        )
        _trace(
            state,
            "visualization_selection",
            duration_ms=int((time.perf_counter() - started) * 1_000),
            detail=f"选择图表：{state.chart.type}",
        )
        return state


class SummaryNode:
    def __init__(self, llm: BaseLLM) -> None:
        self.llm = llm

    async def run(self, state: AgentState) -> AgentState:
        started = time.perf_counter()
        try:
            summary = await self.llm.summarize_result(
                question=state.question,
                intent=state.intent,
                columns=state.columns,
                rows=state.rows,
                truncated=state.truncated,
            )
            state.summary = summary.summary
            state.highlights = summary.highlights
            status = "completed"
            detail = "已根据真实查询结果生成总结。"
        except Exception as exc:
            state.summary = (
                "未查询到符合条件的数据。"
                if not state.rows
                else f"查询返回 {state.row_count} 行数据，请结合表格和图表查看。"
            )
            state.highlights = []
            status = "fallback"
            detail = f"总结模型不可用，已使用确定性摘要：{exc}"
        _trace(
            state,
            "result_summary",
            duration_ms=int((time.perf_counter() - started) * 1_000),
            status=status,
            detail=detail,
        )
        return state

