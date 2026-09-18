from sql_agent.agent.intent import IntentClassifier, IntentType


def test_percentage_question_prefers_distribution_intent() -> None:
    result = IntentClassifier().classify("各订单状态的订单数量占比是多少")
    assert result.intent == IntentType.DISTRIBUTION

