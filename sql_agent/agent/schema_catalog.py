from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import Engine, inspect

from sql_agent.core.exceptions import AgentQueryError


class ColumnSchema(BaseModel):
    name: str
    type: str
    nullable: bool = True
    primary_key: bool = False


class TableSchema(BaseModel):
    name: str
    description: str
    columns: list[ColumnSchema]
    foreign_keys: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


TABLE_METADATA: dict[str, dict[str, Any]] = {
    "users": {
        "description": "用户注册与基础画像；新增用户数使用 users.created_at 按注册日期统计。",
        "keywords": ["用户", "新增", "注册", "会员", "客户", "活跃", "城市", "年龄", "性别"],
        "column_keywords": {
            "created_at": ["新增", "注册", "最近", "每天", "增长"],
            "city": ["城市", "地区", "区域"],
            "age": ["年龄", "年龄段"],
            "status": ["状态", "封禁", "活跃"],
        },
    },
    "orders": {
        "description": "订单主表；包含状态、金额、下单时间和用户外键。",
        "keywords": ["订单", "下单", "成交", "客单价", "取消", "支付", "状态"],
        "column_keywords": {
            "created_at": ["最近", "每天", "上月", "本月", "趋势"],
            "status": ["状态", "取消", "退款"],
            "total_amount": ["订单金额", "成交额", "客单价"],
            "user_id": ["用户", "客户"],
        },
    },
    "order_items": {
        "description": "订单商品明细；销售额通常由 quantity * unit_price 计算。",
        "keywords": ["商品明细", "购买数量", "销量", "件数", "销售额", "产品排名"],
        "column_keywords": {
            "quantity": ["数量", "销量", "件数"],
            "unit_price": ["价格", "销售额", "金额"],
            "product_id": ["产品", "商品"],
        },
    },
    "products": {
        "description": "商品维度表；包含商品名称、价格、成本、库存和上下架状态。",
        "keywords": ["商品", "产品", "库存", "价格", "畅销", "前十", "毛利", "成本"],
        "column_keywords": {
            "name": ["商品名", "产品名", "名称"],
            "category_id": ["分类", "品类", "类目"],
            "stock_quantity": ["库存", "缺货"],
            "status": ["状态", "下架", "停售"],
        },
    },
    "categories": {
        "description": "商品分类维度表；用于按品类聚合分析。",
        "keywords": ["分类", "品类", "类目", "大类"],
        "column_keywords": {"name": ["分类名称", "品类名称"]},
    },
    "sales": {
        "description": "销售事实表；有效销售额建议使用 sales_amount - refund_amount。",
        "keywords": ["销售", "销售额", "营收", "流水", "趋势", "渠道", "退款", "每天"],
        "column_keywords": {
            "sale_date": ["每天", "最近", "趋势", "按月", "按日"],
            "sales_amount": ["销售额", "营收", "流水"],
            "refund_amount": ["退款", "退货"],
            "channel": ["渠道", "来源"],
            "status": ["状态", "退款", "异常"],
        },
    },
}

INTENT_BOOST: dict[str, dict[str, int]] = {
    "trend": {"users": 4, "sales": 5, "orders": 2},
    "ranking": {"products": 5, "order_items": 5, "sales": 3, "orders": 3},
    "distribution": {"categories": 4, "products": 3, "orders": 2, "sales": 2},
    "comparison": {"products": 2, "categories": 2, "sales": 2},
    "count": {"users": 3, "orders": 3, "products": 1, "sales": 2},
    "detail": {"orders": 3, "users": 2, "products": 2, "sales": 2},
    "analytics": {"sales": 2, "orders": 1, "products": 1},
}


@dataclass
class RetrievalResult:
    tables: list[TableSchema] = field(default_factory=list)
    scores: dict[str, int] = field(default_factory=dict)

    @property
    def table_names(self) -> list[str]:
        return [table.name for table in self.tables]


class SchemaCatalog:
    def __init__(self, engine: Engine, allowed_tables: tuple[str, ...] | list[str]) -> None:
        self.engine = engine
        self.allowed_tables = tuple(allowed_tables)
        self._tables = self._load_tables()

    def _load_tables(self) -> dict[str, TableSchema]:
        inspector = inspect(self.engine)
        available = set(inspector.get_table_names())
        missing = [name for name in self.allowed_tables if name not in available]
        if missing:
            raise AgentQueryError(
                f"数据库缺少允许表：{', '.join(missing)}。请先执行初始化或种子脚本。"
            )

        tables: dict[str, TableSchema] = {}
        for table_name in self.allowed_tables:
            metadata = TABLE_METADATA.get(table_name, {})
            columns = []
            for column in inspector.get_columns(table_name):
                columns.append(
                    ColumnSchema(
                        name=column["name"],
                        type=str(column["type"]),
                        nullable=bool(column.get("nullable", True)),
                        primary_key=bool(column.get("primary_key", False)),
                    )
                )
            foreign_keys = [
                f"{item['constrained_columns'][0]} -> {item['referred_table']}."
                f"{item['referred_columns'][0]}"
                for item in inspector.get_foreign_keys(table_name)
                if item.get("constrained_columns") and item.get("referred_columns")
            ]
            tables[table_name] = TableSchema(
                name=table_name,
                description=metadata.get("description", ""),
                columns=columns,
                foreign_keys=foreign_keys,
                keywords=metadata.get("keywords", []),
            )
        return tables

    def list_tables(self) -> list[TableSchema]:
        return [self._tables[name] for name in self.allowed_tables if name in self._tables]

    def retrieve(
        self,
        question: str,
        *,
        intent: str = "analytics",
        max_tables: int = 4,
    ) -> RetrievalResult:
        normalized = question.lower().replace(" ", "")
        scores: dict[str, int] = {}

        for table_name in self._tables:
            metadata = TABLE_METADATA.get(table_name, {})
            score = 0
            if table_name in normalized:
                score += 8
            for keyword in metadata.get("keywords", []):
                if keyword in normalized:
                    score += 4
            for column_name, keywords in metadata.get("column_keywords", {}).items():
                if any(keyword in normalized for keyword in keywords):
                    score += 2
                if column_name in normalized:
                    score += 3
            score += INTENT_BOOST.get(intent, {}).get(table_name, 0)
            scores[table_name] = score

        ranked = sorted(
            scores.items(),
            key=lambda item: (-item[1], self.allowed_tables.index(item[0])),
        )
        positive = [name for name, score in ranked if score > 0]
        if not positive:
            positive = ["users", "orders", "products"]
        selected_names = positive[:max_tables]
        return RetrievalResult(
            tables=[self._tables[name] for name in selected_names],
            scores=scores,
        )

    @staticmethod
    def to_prompt(retrieval: RetrievalResult, dialect: str) -> str:
        blocks: list[str] = []
        for table in retrieval.tables:
            column_lines = [
                f"- {column.name} {column.type}"
                f"{' PRIMARY KEY' if column.primary_key else ''}"
                f"{' NULLABLE' if column.nullable and not column.primary_key else ' NOT NULL'}"
                for column in table.columns
            ]
            foreign_key_text = "\n".join(f"- {item}" for item in table.foreign_keys) or "- 无"
            blocks.append(
                "\n".join(
                    [
                        f"表 {table.name}：{table.description}",
                        "字段：",
                        *column_lines,
                        "外键：",
                        foreign_key_text,
                    ]
                )
            )
        return (
            f"数据库方言：{dialect}\n"
            "业务规则：\n"
            "- orders.status 的成交状态为 paid、shipped、completed；cancelled 不计成交。\n"
            "- 销售额优先使用 order_items.quantity * order_items.unit_price - "
            "order_items.discount_amount；若使用 sales 表则使用 sales_amount - refund_amount。\n"
            "- 统计每日数据时应补齐日期粒度，但不要凭空生成数据库中不存在的日期。\n\n"
            + "\n\n".join(blocks)
        )


