from __future__ import annotations

import json
import re
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from sql_agent.agent.prompts import (
    SQL_SYSTEM_PROMPT,
    SUMMARY_SYSTEM_PROMPT,
    build_sql_user_prompt,
    build_summary_user_prompt,
)
from sql_agent.core.exceptions import LLMProviderError
from sql_agent.llm.base import BaseLLM, ResultSummary, SQLGeneration

T = TypeVar("T", bound=BaseModel)


class OpenAICompatibleLLM(BaseLLM):
    def __init__(
        self,
        *,
        provider_name: str,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: int = 60,
        temperature: float = 0,
    ) -> None:
        if not base_url:
            raise LLMProviderError("LLM 基础地址为空。")
        if not api_key:
            raise LLMProviderError(
                f"未配置 {provider_name} API Key，请设置 LLM_API_KEY 或供应商标准环境变量。"
            )
        self.provider_name = provider_name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.timeout = httpx.Timeout(timeout_seconds, connect=15)

    async def _complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise LLMProviderError(
                f"LLM 请求失败，状态码 {exc.response.status_code}。",
                detail=detail,
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"LLM 网络请求失败：{exc}") from exc

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("LLM 响应结构不符合 OpenAI 兼容格式。") from exc

        if not isinstance(content, str):
            raise LLMProviderError("LLM 返回内容不是文本。")
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                "LLM 未返回合法 JSON。",
                detail=content[:500],
            ) from exc
        try:
            return response_model.model_validate(parsed)
        except ValidationError as exc:
            raise LLMProviderError(
                "LLM JSON 字段不符合约定。",
                detail=exc.errors(include_url=False),
            ) from exc

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
        return await self._complete_json(
            system_prompt=SQL_SYSTEM_PROMPT,
            user_prompt=build_sql_user_prompt(
                question=question,
                intent=intent,
                schema_context=schema_context,
                max_rows=max_rows,
                previous_error=previous_error,
            ),
            response_model=SQLGeneration,
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
        return await self._complete_json(
            system_prompt=SUMMARY_SYSTEM_PROMPT,
            user_prompt=build_summary_user_prompt(
                question=question,
                intent=intent,
                columns=columns,
                rows=rows,
                truncated=truncated,
            ),
            response_model=ResultSummary,
        )

