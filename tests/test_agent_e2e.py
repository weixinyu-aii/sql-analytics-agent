import pytest

from sql_agent.agent.graph import AnalyticsAgent
from sql_agent.agent.schema_catalog import SchemaCatalog
from sql_agent.db.models import Base
from sql_agent.db.seed import seed_database
from sql_agent.db.session import build_engine
from sql_agent.llm.mock import MockLLM
from sql_agent.security.sql_guard import SQLGuard
from sql_agent.services.executor import ReadOnlyQueryExecutor

ALLOWED_TABLES = ("categories", "products", "users", "orders", "order_items", "sales")


@pytest.fixture()
def agent(tmp_path) -> AnalyticsAgent:
    database_url = f"sqlite:///{tmp_path / 'analytics.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    seed_database(engine, force=True, scale=0.04)

    catalog = SchemaCatalog(engine, ALLOWED_TABLES)
    executor = ReadOnlyQueryExecutor(database_url=database_url, dialect="sqlite", max_rows=200)
    llm = MockLLM()
    return AnalyticsAgent(
        catalog=catalog,
        llm=llm,
        guard=SQLGuard(allowed_tables=ALLOWED_TABLES, max_rows=200),
        executor=executor,
        dialect="sqlite",
        max_rows=200,
        max_retries=2,
    )


async def test_user_trend_end_to_end(agent: AnalyticsAgent) -> None:
    result = await agent.run("最近 7 天每天新增用户数是多少")
    assert result.intent == "trend"
    assert result.row_count >= 1
    assert result.chart.type == "line"
    assert result.summary
    assert "users" in result.relevant_tables
    assert "LIMIT" in result.sql.upper()


async def test_product_ranking_end_to_end(agent: AnalyticsAgent) -> None:
    result = await agent.run("上个月销售额最高的前 10 个产品是什么")
    assert result.intent == "ranking"
    assert result.row_count >= 1
    assert result.chart.type == "bar"
    assert {"products", "orders", "order_items"}.issubset(set(result.relevant_tables))


