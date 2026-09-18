from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from sql_agent.llm.base import BaseLLM, ResultSummary, SQLGeneration


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _date_value(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _day_window(column: str, days: int, dialect: str) -> str:
    days_back = max(days - 1, 0)
    if dialect == "postgresql":
        return (
            f"{column} >= CURRENT_DATE - INTERVAL '{days_back} days' "
            f"AND {column} < CURRENT_DATE + INTERVAL '1 day'"
        )
    if dialect == "mysql":
        return (
            f"{column} >= DATE_SUB(CURDATE(), INTERVAL {days_back} DAY) "
            f"AND {column} < DATE_ADD(CURDATE(), INTERVAL 1 DAY)"
        )
    return (
        f"DATE({column}) >= DATE('now', '-{days_back} day') "
        f"AND DATE({column}) < DATE('now', '+1 day')"
    )


def _last_month_filter(column: str, dialect: str) -> str:
    if dialect == "postgresql":
        return (
            f"{column} >= date_trunc('month', CURRENT_DATE - INTERVAL '1 month') "
            f"AND {column} < date_trunc('month', CURRENT_DATE)"
        )
    if dialect == "mysql":
        return (
            f"DATE_FORMAT({column}, '%Y-%m') = "
            "DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 1 MONTH), '%Y-%m')"
        )
    return f"strftime('%Y-%m', {column}) = strftime('%Y-%m', 'now', '-1 month')"


def _extract_days(question: str, default: int = 7) -> int:
    match = re.search(r"(?:最近|近)\s*(\d{1,3})\s*天", question)
    return min(max(int(match.group(1)), 1), 90) if match else default


def _extract_top_n(question: str, default: int = 10) -> int:
    match = re.search(r"(?:前|top)\s*(\d{1,3})", question.lower())
    return min(max(int(match.group(1)), 1), 50) if match else default


class MockLLM(BaseLLM):
    """Deterministic demo provider so the project runs without an API key."""

    provider_name = "mock"

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
        normalized = question.lower().replace(" ", "")
        days = _extract_days(question)
        top_n = min(_extract_top_n(question), max_rows)
        query_limit = min(max_rows, 200)
        date_col = "DATE(created_at) AS day"

        if ("新增用户" in normalized or "用户数" in normalized) and (
            "每天" in normalized or "每日" in normalized or intent == "trend"
        ):
            return SQLGeneration(
                sql=(
                    f"SELECT {date_col}, COUNT(*) AS new_users "
                    "FROM users "
                    f"WHERE {_day_window('created_at', days, dialect)} "
                    f"GROUP BY DATE(created_at) ORDER BY day LIMIT {query_limit}"
                ),
                explanation=f"按注册日期统计最近 {days} 天的每日新增用户数。",
                tables_used=["users"],
            )

        if "新增用户" in normalized or ("用户" in normalized and intent == "count"):
            return SQLGeneration(
                sql=(
                    "SELECT COUNT(*) AS user_count FROM users "
                    f"WHERE {_day_window('created_at', days, dialect)} LIMIT 1"
                ),
                explanation=f"统计最近 {days} 天新增用户总数。",
                tables_used=["users"],
            )

        if "产品" in normalized and ("销售" in normalized or "销量" in normalized):
            month_filter = (
                _last_month_filter("o.created_at", dialect)
                if "上个月" in normalized
                else _day_window("o.created_at", 30, dialect)
            )
            return SQLGeneration(
                sql=(
                    "SELECT p.name AS product_name, "
                    "ROUND(SUM(oi.quantity * oi.unit_price - oi.discount_amount), 2) "
                    "AS sales_amount "
                    "FROM order_items oi "
                    "JOIN orders o ON o.id = oi.order_id "
                    "JOIN products p ON p.id = oi.product_id "
                    "WHERE o.status IN ('paid', 'shipped', 'completed') "
                    f"AND {month_filter} "
                    "GROUP BY p.id, p.name "
                    f"ORDER BY sales_amount DESC LIMIT {top_n}"
                ),
                explanation=f"按月内成交订单统计销售额最高的前 {top_n} 个产品。",
                tables_used=["order_items", "orders", "products"],
                assumptions=["排除已取消订单，商品销售额已扣除明细优惠。"],
            )

        if ("销售额" in normalized or "营收" in normalized) and (
            "每天" in normalized or "每日" in normalized or intent == "trend"
        ):
            return SQLGeneration(
                sql=(
                    "SELECT DATE(s.sale_date) AS day, "
                    "ROUND(SUM(s.sales_amount - s.refund_amount), 2) AS sales_amount "
                    "FROM sales s "
                    "WHERE s.status IN ('normal', 'refunded') "
                    f"AND {_day_window('s.sale_date', days, dialect)} "
                    f"GROUP BY DATE(s.sale_date) ORDER BY day LIMIT {query_limit}"
                ),
                explanation=f"按销售日期统计最近 {days} 天的净销售额。",
                tables_used=["sales"],
                assumptions=["净销售额等于 sales_amount 减去 refund_amount。"],
            )

        if ("分类" in normalized or "品类" in normalized) and "销售" in normalized:
            return SQLGeneration(
                sql=(
                    "SELECT c.name AS category_name, "
                    "ROUND(SUM(s.sales_amount - s.refund_amount), 2) AS sales_amount "
                    "FROM sales s "
                    "JOIN products p ON p.id = s.product_id "
                    "JOIN categories c ON c.id = p.category_id "
                    "WHERE s.status IN ('normal', 'refunded') "
                    "GROUP BY c.id, c.name ORDER BY sales_amount DESC "
                    f"LIMIT {query_limit}"
                ),
                explanation="按商品分类汇总净销售额。",
                tables_used=["sales", "products", "categories"],
            )

        if ("订单" in normalized and "状态" in normalized) or (
            "订单" in normalized and intent == "distribution"
        ):
            return SQLGeneration(
                sql=(
                    "SELECT status, COUNT(*) AS order_count, "
                    "ROUND(SUM(total_amount), 2) AS gross_amount "
                    "FROM orders GROUP BY status ORDER BY order_count DESC "
                    f"LIMIT {query_limit}"
                ),
                explanation="按订单状态统计订单数量和订单金额。",
                tables_used=["orders"],
            )

        if "城市" in normalized and "用户" in normalized:
            return SQLGeneration(
                sql=(
                    "SELECT COALESCE(city, '未知') AS city, COUNT(*) AS user_count "
                    "FROM users GROUP BY COALESCE(city, '未知') "
                    f"ORDER BY user_count DESC LIMIT {query_limit}"
                ),
                explanation="按城市统计用户数量，空值归为未知。",
                tables_used=["users"],
            )

        if "订单" in normalized:
            return SQLGeneration(
                sql=(
                    "SELECT order_no, status, total_amount, created_at "
                    "FROM orders ORDER BY created_at DESC "
                    f"LIMIT {min(query_limit, 100)}"
                ),
                explanation="展示最近订单明细。",
                tables_used=["orders"],
            )

        if "产品" in normalized or "商品" in normalized:
            return SQLGeneration(
                sql=(
                    "SELECT name, price, stock_quantity, status "
                    "FROM products ORDER BY stock_quantity ASC, price DESC "
                    f"LIMIT {min(query_limit, 100)}"
                ),
                explanation="展示库存较低的商品概况。",
                tables_used=["products"],
            )

        return SQLGeneration(
            sql=(
                "SELECT 'users' AS metric, COUNT(*) AS value FROM users "
                "UNION ALL SELECT 'orders', COUNT(*) FROM orders "
                "UNION ALL SELECT 'products', COUNT(*) FROM products "
                f"LIMIT {query_limit}"
            ),
            explanation="由于问题较泛，返回核心业务表的数据量概览。",
            tables_used=["users", "orders", "products"],
            assumptions=["该问题未匹配到明确指标，请补充时间范围和业务对象。"],
        )

    async def summarize_result(
        self,
        *,
        question: str,
        intent: str,
        columns: list[str],
        rows: list[list[object]],
        truncated: bool,
    ) -> ResultSummary:
        if not rows:
            return ResultSummary(
                summary="未查询到符合条件的数据，请检查时间范围或筛选条件。",
                highlights=["查询结果为空。"],
            )

        numeric_indexes = [
            index
            for index in range(len(columns))
            if any(_number(row[index]) is not None for row in rows if index < len(row))
        ]
        metric_index = numeric_indexes[-1] if numeric_indexes else None
        label_index = 0 if metric_index != 0 else min(1, len(columns) - 1)
        highlights: list[str] = []
        summary = ""

        if metric_index is not None and intent == "trend" and len(rows) > 1:
            values = [_number(row[metric_index]) for row in rows]
            numeric_values = [value for value in values if value is not None]
            if numeric_values:
                first, last = numeric_values[0], numeric_values[-1]
                max_value = max(numeric_values)
                max_row = next(row for row in rows if _number(row[metric_index]) == max_value)
                if last > first:
                    direction = "整体呈上升趋势"
                elif last < first:
                    direction = "整体呈下降趋势"
                else:
                    direction = "整体基本持平"
                summary = (
                    f"最近 {len(rows)} 个时间点从 {first:,.2f} 变化到 {last:,.2f}，"
                    f"{direction}；{_date_value(max_row[label_index])} 的数值最高，"
                    f"为 {max_value:,.2f}。"
                )
                highlights.append(f"最高值：{_date_value(max_row[label_index])} / {max_value:,.2f}")
        elif metric_index is not None and intent in {"ranking", "comparison", "distribution"}:
            ranked_rows = sorted(
                rows,
                key=lambda row: _number(row[metric_index]) or float("-inf"),
                reverse=True,
            )
            top = ranked_rows[0]
            metric = _number(top[metric_index]) or 0
            label = _date_value(top[label_index])
            summary = f"排名第一的是“{label}”，对应指标为 {metric:,.2f}。"
            highlights.append(f"最高项：{label} / {metric:,.2f}")
            if intent == "distribution":
                total = sum(
                    value for row in rows if (value := _number(row[metric_index])) is not None
                )
                share = metric / total * 100 if total else 0
                summary += f" 占全部结果的 {share:.1f}%。"
                highlights.append(f"最高项占比：{share:.1f}%")
        elif len(rows) == 1:
            first_row = rows[0]
            if metric_index is not None:
                metric = _number(first_row[metric_index]) or 0
                summary = f"查询结果为 {metric:,.2f}。"
                highlights.append(f"{columns[metric_index]}：{metric:,.2f}")
            else:
                summary = "查询返回了 1 条记录。"
        else:
            summary = (
                f"查询共返回 {len(rows)} 行、{len(columns)} 列；"
                "建议结合下方明细和图表继续筛选。"
            )

        if truncated:
            summary += " 查询结果已达到返回上限，仅展示部分数据。"
            highlights.append("结果已截断。")
        if not summary:
            summary = f"查询共返回 {len(rows)} 行数据。"
        return ResultSummary(summary=summary, highlights=highlights)

