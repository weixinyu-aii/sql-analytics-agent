from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sql_agent.frontend.api_client import AnalyticsAPIClient  # noqa: E402

st.set_page_config(
    page_title="智能数据分析 Agent",
    page_icon=":material/analytics:",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(ttl=10)
def load_health() -> dict[str, Any]:
    return AnalyticsAPIClient().health()


@st.cache_data(ttl=300)
def load_examples() -> list[dict[str, str]]:
    return AnalyticsAPIClient().examples().get("examples", [])


def render_chart(result: dict[str, Any]) -> None:
    chart = result.get("chart") or {}
    chart_type = chart.get("type", "table")
    columns = result.get("columns", [])
    rows = result.get("rows", [])
    if chart_type == "table" or not rows or not columns:
        return

    frame = pd.DataFrame(rows, columns=columns)
    x = chart.get("x")
    y_values = chart.get("y") or []
    y = y_values[0] if y_values else None
    if x not in frame.columns or y not in frame.columns:
        return

    color = chart.get("color") if chart.get("color") in frame.columns else None
    if chart_type == "line":
        st.line_chart(frame, x=x, y=y, color=color, height=420)
    elif chart_type == "bar":
        st.bar_chart(
            frame,
            x=x,
            y=y,
            color=color,
            horizontal=chart.get("orientation") == "h",
            sort=False,
            height=420,
        )
    elif chart_type == "pie":
        tooltip = [
            alt.Tooltip(field=x, type="nominal"),
            alt.Tooltip(field=y, type="quantitative"),
        ]
        figure = (
            alt.Chart(frame)
            .mark_arc(innerRadius=45)
            .encode(
                theta=alt.Theta(field=y, type="quantitative"),
                color=alt.Color(field=x, type="nominal", title=x),
                tooltip=tooltip,
            )
        )
        st.altair_chart(figure, width="stretch", height=420)


def render_result(result: dict[str, Any]) -> None:
    with st.container(border=True):
        st.subheader("分析结论")
        st.write(result.get("summary", "查询完成。"))
        metrics = st.columns(4)
        metrics[0].metric("返回行数", result.get("row_count", 0))
        metrics[1].metric("执行耗时", f'{result.get("execution_ms", 0)} ms')
        metrics[2].metric("Agent 尝试", result.get("attempts", 1))
        metrics[3].metric("意图", result.get("intent", "analytics"))
        for highlight in result.get("highlights", []):
            st.caption(f"• {highlight}")

    render_chart(result)
    columns = result.get("columns", [])
    rows = result.get("rows", [])
    if columns:
        frame = pd.DataFrame(rows, columns=columns)
        st.dataframe(
            frame,
            width="stretch",
            hide_index=True,
            height=min(420, 42 + 35 * len(frame)),
        )

    with st.expander("SQL 与安全校验"):
        st.code(result.get("sql", ""), language="sql")
        st.write(result.get("sql_explanation") or "无额外说明。")
        safety = result.get("safety") or {}
        st.caption(
            f'白名单表：{", ".join(safety.get("tables", [])) or "无"} | '
            f'强制 LIMIT：{safety.get("applied_limit", "-")}'
        )
        if result.get("assumptions"):
            st.markdown("**模型假设**")
            for assumption in result["assumptions"]:
                st.write(f"- {assumption}")

    with st.expander("Agent 执行轨迹"):
        trace_rows = [
            {
                "步骤": item.get("step"),
                "状态": item.get("status"),
                "耗时(ms)": item.get("duration_ms"),
                "说明": item.get("detail"),
            }
            for item in result.get("trace", [])
        ]
        if trace_rows:
            st.dataframe(pd.DataFrame(trace_rows), width="stretch", hide_index=True)
        st.caption(
            f'LLM Provider：{result.get("llm_provider", "unknown")} | '
            f'相关表：{", ".join(result.get("relevant_tables", []))}'
        )


st.session_state.setdefault("messages", [])

with st.sidebar:
    st.title("智能数据分析 Agent")
    try:
        health = load_health()
        if health.get("database"):
            st.success(f'服务正常 · {health.get("dialect")}')
        else:
            st.warning("数据库连接异常")
        st.caption(
            f'模型：{health.get("llm_provider")} / {health.get("llm_model")}'
        )
        st.markdown("**允许访问的表**")
        st.code("\n".join(health.get("tables", [])), language="text")
    except Exception as exc:
        st.error(str(exc))

    st.divider()
    st.markdown("**查询安全**")
    st.caption("仅允许 SELECT，自动限制返回行数，并通过只读数据库账号执行。")

st.title("智能数据分析 Agent")
st.caption("自然语言提问 → Schema 检索 → 安全 SQL → 只读执行 → 可视化 → 数据总结")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message["role"] == "user":
            st.markdown(message["content"])
        elif message.get("result"):
            render_result(message["result"])
        else:
            st.error(message.get("content", "查询失败"))

pending_question = st.session_state.pop("pending_question", None)
if not st.session_state.messages and pending_question is None:
    try:
        examples = load_examples()
        questions = [item["question"] for item in examples]
        selection = st.pills(
            "试试这些问题",
            questions,
            key="suggestion",
            width="stretch",
            wrap=True,
        )
        if selection:
            st.session_state.pending_question = selection
            st.rerun()
    except Exception:
        pass

if pending_question is None:
    pending_question = st.session_state.pop("pending_question", None)

typed_question = st.chat_input(
    "例如：最近 7 天每天新增用户数是多少？",
    max_chars=500,
    submit_mode="disable",
)
question = pending_question or typed_question

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        status = st.status("正在分析数据", type="compact", expanded=True)
        try:
            status.write("检索相关业务表和字段")
            status.write("生成 SQL 并执行安全校验")
            status.write("执行只读查询并生成结果总结")
            result = AnalyticsAPIClient().query(question)
            status.update(label=f'分析完成 · {result.get("execution_ms", 0)} ms', state="complete")
            render_result(result)
            st.session_state.messages.append(
                {"role": "assistant", "result": result, "content": result.get("summary", "")}
            )
        except Exception as exc:
            status.update(label="查询失败", state="error")
            st.error(str(exc))
            st.session_state.messages.append(
                {"role": "assistant", "content": str(exc), "result": None}
            )

