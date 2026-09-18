from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).parents[1] / "sql_agent" / "frontend" / "streamlit_app.py"


def test_streamlit_app_renders_without_exception() -> None:
    app = AppTest.from_file(APP_PATH).run(timeout=20)
    assert not app.exception
    assert app.title


def test_streamlit_app_renders_agent_result() -> None:
    result = {
        "summary": "测试结论",
        "row_count": 2,
        "execution_ms": 12,
        "attempts": 1,
        "intent": "trend",
        "columns": ["day", "new_users"],
        "rows": [["2026-09-17", 10], ["2026-09-18", 12]],
        "chart": {"type": "line", "x": "day", "y": ["new_users"]},
        "sql": "SELECT 1",
        "sql_explanation": "测试",
        "safety": {"tables": ["users"], "applied_limit": 200},
        "trace": [],
        "relevant_tables": ["users"],
        "llm_provider": "mock",
    }
    app = AppTest.from_file(APP_PATH)
    app.session_state["messages"] = [
        {"role": "assistant", "result": result, "content": result["summary"]}
    ]
    app.run(timeout=20)
    assert not app.exception
    assert app.dataframe

