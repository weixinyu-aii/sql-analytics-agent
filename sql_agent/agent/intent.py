from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel


class IntentType(StrEnum):
    TREND = "trend"
    RANKING = "ranking"
    DISTRIBUTION = "distribution"
    COMPARISON = "comparison"
    COUNT = "count"
    DETAIL = "detail"
    ANALYTICS = "analytics"


class IntentResult(BaseModel):
    intent: IntentType
    confidence: float
    matched_keywords: list[str]


class IntentClassifier:
    KEYWORDS: dict[IntentType, tuple[str, ...]] = {
        IntentType.TREND: (
            "趋势",
            "每天",
            "每日",
            "按天",
            "按月",
            "最近",
            "近",
            "走势",
            "增长",
            "下降",
        ),
        IntentType.RANKING: (
            "排名",
            "排行",
            "前十",
            "top",
            "最高",
            "最多",
            "最好",
            "最畅销",
            "销售额前",
        ),
        IntentType.DISTRIBUTION: ("占比", "比例", "分布", "构成", "结构", "各渠道"),
        IntentType.COMPARISON: ("对比", "比较", "同比", "环比", "差异", "变化率"),
        IntentType.COUNT: ("多少", "数量", "总数", "人数", "用户数", "订单数", "销售额是"),
        IntentType.DETAIL: ("明细", "列表", "列出", "查看", "展示", "详情"),
    }

    def classify(self, question: str) -> IntentResult:
        normalized = question.lower().replace(" ", "")
        scores: dict[IntentType, int] = {}
        matches: dict[IntentType, list[str]] = {}

        for intent, keywords in self.KEYWORDS.items():
            found = [keyword for keyword in keywords if keyword in normalized]
            matches[intent] = found
            scores[intent] = len(found) * 2
            if intent == IntentType.TREND and re.search(r"近\d+天|最近\d+天", normalized):
                scores[intent] += 4
            if intent == IntentType.RANKING and re.search(r"前\d+|top\d+", normalized):
                scores[intent] += 4
            if intent == IntentType.DISTRIBUTION and found:
                scores[intent] += 4

        if not any(scores.values()):
            return IntentResult(
                intent=IntentType.ANALYTICS,
                confidence=0.45,
                matched_keywords=[],
            )

        best_intent, best_score = max(scores.items(), key=lambda item: item[1])
        confidence = min(0.98, 0.55 + best_score * 0.06)
        return IntentResult(
            intent=best_intent,
            confidence=confidence,
            matched_keywords=matches[best_intent],
        )

