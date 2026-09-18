from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from sql_agent.agent.graph import AnalyticsAgent
from sql_agent.agent.schema_catalog import SchemaCatalog
from sql_agent.db.models import Base
from sql_agent.db.seed import seed_database
from sql_agent.db.session import build_engine
from sql_agent.llm.mock import MockLLM
from sql_agent.security.sql_guard import SQLGuard
from sql_agent.services.executor import ReadOnlyQueryExecutor

ALLOWED_TABLES = ("categories", "products", "users", "orders", "order_items", "sales")
GOLDEN_CASES = [
    {
        "question": "最近 7 天每天新增用户数是多少",
        "expected_tables": {"users"},
        "expected_chart": "line",
    },
    {
        "question": "上个月销售额最高的前 10 个产品是什么",
        "expected_tables": {"order_items", "orders", "products"},
        "expected_chart": "bar",
    },
    {
        "question": "各订单状态的订单数量占比是多少",
        "expected_tables": {"orders"},
        "expected_chart": "pie",
    },
    {
        "question": "最近 7 天每天销售额趋势如何",
        "expected_tables": {"sales"},
        "expected_chart": "line",
    },
]


async def evaluate() -> list[dict[str, object]]:
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{Path(directory) / 'evaluation.db'}"
        engine = build_engine(database_url)
        Base.metadata.create_all(engine)
        seed_database(engine, force=True, scale=0.05)

        executor = ReadOnlyQueryExecutor(
            database_url=database_url,
            dialect="sqlite",
            max_rows=200,
        )
        agent = AnalyticsAgent(
            catalog=SchemaCatalog(engine, ALLOWED_TABLES),
            llm=MockLLM(),
            guard=SQLGuard(allowed_tables=ALLOWED_TABLES, max_rows=200),
            executor=executor,
            dialect="sqlite",
            max_rows=200,
            max_retries=2,
        )

        report: list[dict[str, object]] = []
        for case in GOLDEN_CASES:
            expected_tables = case["expected_tables"]
            try:
                result = await agent.run(str(case["question"]))
                actual_tables = set(result.relevant_tables)
                recall = len(expected_tables & actual_tables) / len(expected_tables)
                report.append(
                    {
                        "question": case["question"],
                        "execution_success": True,
                        "schema_recall": round(recall, 3),
                        "chart_accuracy": result.chart.type == case["expected_chart"],
                        "row_count": result.row_count,
                        "attempts": result.attempts,
                    }
                )
            except Exception as exc:
                report.append(
                    {
                        "question": case["question"],
                        "execution_success": False,
                        "error": str(exc),
                    }
                )

        executor.dispose()
        engine.dispose()
        return report


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    report = asyncio.run(evaluate())
    summary = {
        "cases": len(report),
        "execution_success_rate": round(
            sum(bool(item["execution_success"]) for item in report) / len(report), 3
        ),
        "schema_recall_at_k": round(
            sum(float(item.get("schema_recall", 0)) for item in report) / len(report), 3
        ),
        "chart_accuracy": round(
            sum(bool(item.get("chart_accuracy")) for item in report) / len(report), 3
        ),
    }
    print(json.dumps({"summary": summary, "details": report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()



