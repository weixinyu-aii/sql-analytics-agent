SQL_SYSTEM_PROMPT = """
你是企业级 Text2SQL 分析助手。你必须严格依据用户问题和给定数据库表结构生成 SQL。

硬性规则：
1. 只能使用提供的表和字段，禁止猜测不存在的字段、表或业务含义。
2. 只生成一条只读 SELECT 或 WITH ... SELECT 查询。
3. 禁止 INSERT、UPDATE、DELETE、DROP、ALTER、TRUNCATE、CREATE、GRANT、REVOKE、
   存储过程、文件读写、系统表或跨库查询。
4. 所有查询必须有明确的记录数上限；即使问题要求全量，也最多返回 200 行。
5. 不要输出 Markdown 代码块或解释性前后缀，只输出 JSON。
6. JSON 结构必须为：
   {"sql":"...", "explanation":"...", "tables_used":["..."], "assumptions":["..."]}
7. 表名列名必须来自给定 schema；别名可以自定义。
8. 日期逻辑必须使用给定数据库方言支持的语法。
9. 统计销售额时排除 cancelled 订单，并考虑退款金额；不要擅自把 NULL 当成 0。
10. 如果信息不足，优先返回一个合理的聚合查询，并把不确定性写在 assumptions 中。
""".strip()


SUMMARY_SYSTEM_PROMPT = """
你是数据结果解读助手。你只能依据输入的 query_result 得出结论，不能编造数据、原因或业务背景。
要求：
- 用中文给出 1 到 3 句话的简洁总结。
- 明确提到最重要的数值、最高/最低项或趋势方向。
- 如果行数为 0，说明未查询到符合条件的数据。
- 如果结果被截断，必须提示用户结果已截断。
- 不把相关性解释成因果关系。
- 只输出 JSON：
  {"summary":"...", "highlights":["..."]}
""".strip()


def build_sql_user_prompt(
    *,
    question: str,
    intent: str,
    schema_context: str,
    max_rows: int,
    previous_error: str | None = None,
) -> str:
    retry_text = ""
    if previous_error:
        retry_text = (
            "\n上一次 SQL 失败，原因如下。请修正后重新生成，不能重复同一错误：\n"
            f"{previous_error}\n"
        )
    return f"""
用户问题：{question}
识别意图：{intent}

可用表结构：
{schema_context}
{retry_text}
请生成最多返回 {max_rows} 行的分析 SQL，并严格输出约定 JSON。
""".strip()


def build_summary_user_prompt(
    *,
    question: str,
    intent: str,
    columns: list[str],
    rows: list[list[object]],
    truncated: bool,
) -> str:
    import json

    sample = rows[:50]
    return f"""
原始问题：{question}
识别意图：{intent}
结果列：{json.dumps(columns, ensure_ascii=False)}
结果行数：{len(rows)}
是否截断：{"是" if truncated else "否"}
query_result：
{json.dumps(sample, ensure_ascii=False, default=str)}

请严格依据上述真实结果输出 JSON 总结。
""".strip()

