from __future__ import annotations

import re

import sqlglot
from pydantic import BaseModel, Field
from sqlglot import exp
from sqlglot.errors import ParseError

from sql_agent.core.exceptions import SQLSafetyError

FORBIDDEN_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "truncate",
    "create",
    "grant",
    "revoke",
    "merge",
    "call",
    "copy",
    "vacuum",
    "attach",
    "detach",
    "pragma",
    "replace",
    "into",
}
FORBIDDEN_FUNCTIONS = {
    "sleep",
    "pg_sleep",
    "benchmark",
    "load_file",
    "sys_exec",
    "shell_exec",
    "xp_cmdshell",
}

QUERY_NODE_TYPES = tuple(
    node_type
    for node_type in (
        getattr(exp, "Query", None),
        getattr(exp, "Select", None),
        getattr(exp, "Union", None),
        getattr(exp, "Except", None),
        getattr(exp, "Intersect", None),
    )
    if node_type is not None
)


class SQLSafetyResult(BaseModel):
    sql: str
    tables: list[str] = Field(default_factory=list)
    applied_limit: int
    warnings: list[str] = Field(default_factory=list)


class SQLGuard:
    def __init__(
        self,
        *,
        allowed_tables: tuple[str, ...] | list[str],
        max_rows: int = 200,
        max_length: int = 12_000,
    ) -> None:
        self.allowed_tables = {name.lower() for name in allowed_tables}
        self.max_rows = max_rows
        self.max_length = max_length

    def validate(self, sql: str, *, dialect: str) -> SQLSafetyResult:
        cleaned = sql.strip()
        if not cleaned:
            raise SQLSafetyError("模型返回了空 SQL。")
        if len(cleaned) > self.max_length:
            raise SQLSafetyError(f"SQL 长度超过 {self.max_length} 字符限制。")
        if re.search(r"\x00", cleaned):
            raise SQLSafetyError("SQL 包含非法空字符。")

        normalized = re.sub(r"\s+", " ", cleaned).lower().rstrip(";")
        for keyword in FORBIDDEN_KEYWORDS:
            if re.search(rf"\b{keyword}\b", normalized):
                raise SQLSafetyError(f"SQL 包含禁止关键字：{keyword.upper()}。")

        try:
            statements = sqlglot.parse(cleaned, read=dialect)
        except ParseError as exc:
            raise SQLSafetyError(f"SQL 解析失败：{exc}") from exc

        statements = [statement for statement in statements if statement is not None]
        if len(statements) != 1:
            raise SQLSafetyError("只允许执行一条 SQL 语句。")

        statement = statements[0]
        if not isinstance(statement, QUERY_NODE_TYPES):
            raise SQLSafetyError("只允许 SELECT 或 WITH ... SELECT 查询。")
        if not isinstance(statement, (exp.Select, getattr(exp, "Union", exp.Select))):
            # Other query set operations are valid read-only queries only when their root is a query.
            pass

        cte_names = {
            cte.alias_or_name.lower()
            for cte in statement.find_all(exp.CTE)
            if getattr(cte, "alias_or_name", None)
        }
        referenced_tables: list[str] = []
        for table in statement.find_all(exp.Table):
            table_name = table.name.lower()
            if table_name in cte_names:
                continue
            if table_name not in self.allowed_tables:
                raise SQLSafetyError(f"禁止访问白名单以外的表：{table_name}。")
            if table_name not in referenced_tables:
                referenced_tables.append(table_name)

        for function in statement.find_all(exp.Func):
            name = (getattr(function, "name", None) or function.sql_name()).lower()
            if name in FORBIDDEN_FUNCTIONS:
                raise SQLSafetyError(f"禁止调用高风险函数：{name}。")

        node_keys = {node.key.lower() for node in statement.walk()}
        forbidden_nodes = sorted(node_keys & FORBIDDEN_KEYWORDS - {"into"})
        if forbidden_nodes:
            raise SQLSafetyError(f"检测到非只读语法节点：{', '.join(forbidden_nodes)}。")
        if "into" in node_keys:
            raise SQLSafetyError("禁止 SELECT INTO 或其他写入型 INTO 语法。")

        existing_limit = statement.args.get("limit")
        existing_value: int | None = None
        if isinstance(existing_limit, exp.Limit):
            limit_expression = existing_limit.expression
            if isinstance(limit_expression, exp.Literal) and limit_expression.is_int:
                existing_value = int(limit_expression.this)

        warnings: list[str] = []
        if existing_value is None or existing_value > self.max_rows:
            if existing_value is not None:
                warnings.append(
                    f"原 LIMIT {existing_value} 超过上限，已收紧为 {self.max_rows}。"
                )
            applied_limit = self.max_rows
            try:
                statement = statement.limit(self.max_rows)
            except Exception as exc:
                raise SQLSafetyError(f"注入 LIMIT 失败：{exc}") from exc
        else:
            applied_limit = existing_value

        try:
            safe_sql = statement.sql(dialect=dialect, pretty=True)
        except Exception as exc:
            raise SQLSafetyError(f"格式化 SQL 失败：{exc}") from exc

        return SQLSafetyResult(
            sql=safe_sql,
            tables=referenced_tables,
            applied_limit=applied_limit,
            warnings=warnings,
        )



