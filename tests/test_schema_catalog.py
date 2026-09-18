from sqlalchemy import create_engine

from sql_agent.agent.schema_catalog import SchemaCatalog
from sql_agent.db.models import Base


def test_schema_retrieval_selects_relevant_tables(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'schema.db'}")
    Base.metadata.create_all(engine)
    catalog = SchemaCatalog(
        engine,
        ("categories", "products", "users", "orders", "order_items", "sales"),
    )

    user_result = catalog.retrieve("最近 7 天每天新增用户数是多少", intent="trend")
    assert "users" in user_result.table_names

    sales_result = catalog.retrieve("上个月销售额最高的前 10 个产品", intent="ranking")
    assert {"products", "order_items", "orders"}.issubset(set(sales_result.table_names))

