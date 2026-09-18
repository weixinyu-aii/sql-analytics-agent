from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ChartSpec(BaseModel):
    type: str = "table"
    title: str = "查询结果"
    x: str | None = None
    y: list[str] = Field(default_factory=list)
    color: str | None = None
    orientation: str = "v"


def _is_number(value: object) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float, Decimal)):
        return True
    try:
        float(str(value))
        return True
    except (TypeError, ValueError):
        return False


def _is_temporal(column: str, values: list[object]) -> bool:
    name = column.lower()
    if any(token in name for token in ("date", "day", "month", "week", "time", "日期", "月", "日")):
        return True
    for value in values[:5]:
        if isinstance(value, (date, datetime)):
            return True
        if isinstance(value, str) and re.match(r"^\d{4}-\d{2}(-\d{2})?", value):
            return True
    return False


class VisualizationSelector:
    def select(
        self,
        *,
        columns: list[str],
        rows: list[list[object]],
        intent: str,
        question: str,
    ) -> ChartSpec:
        if not rows or len(columns) < 2:
            return ChartSpec(type="table")

        values_by_column = [
            [row[index] for row in rows if index < len(row)]
            for index in range(len(columns))
        ]
        numeric = [
            index
            for index, values in enumerate(values_by_column)
            if not any(token in columns[index].lower() for token in ("_id", "id_"))
            and sum(1 for value in values if _is_number(value)) >= max(1, len(values) // 2)
        ]
        temporal = [
            index
            for index, values in enumerate(values_by_column)
            if _is_temporal(columns[index], values)
        ]
        categories = [index for index in range(len(columns)) if index not in numeric]

        time_index = temporal[0] if temporal else None
        metric_index = numeric[-1] if numeric else None
        category_index = categories[0] if categories else None
        color_index = next((index for index in categories if index != category_index), None)

        if time_index is not None and metric_index is not None:
            chart_type = "line" if intent == "trend" or "趋势" in question else "bar"
            return ChartSpec(
                type=chart_type,
                title="时间趋势" if chart_type == "line" else "按时间汇总",
                x=columns[time_index],
                y=[columns[metric_index]],
                color=columns[color_index] if color_index is not None else None,
            )

        if category_index is not None and metric_index is not None:
            if intent == "distribution" and len(rows) <= 12:
                chart_type = "pie"
                orientation = "v"
            else:
                chart_type = "bar"
                orientation = "h" if intent == "ranking" or len(rows) > 8 else "v"
            return ChartSpec(
                type=chart_type,
                title="占比分布" if chart_type == "pie" else "分类对比",
                x=columns[category_index],
                y=[columns[metric_index]],
                color=columns[color_index] if color_index is not None else None,
                orientation=orientation,
            )

        return ChartSpec(type="table")

