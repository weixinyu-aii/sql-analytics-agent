from __future__ import annotations

import os
from typing import Any

import httpx


class AnalyticsAPIClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (
            base_url or os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")
        ).rstrip("/")
        self.timeout = httpx.Timeout(120, connect=10)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, f"{self.base_url}{path}", **kwargs)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            try:
                detail = exc.response.json().get("detail", exc.response.text)
            except Exception:
                detail = exc.response.text
            if isinstance(detail, dict):
                detail = detail.get("message", str(detail))
            raise RuntimeError(str(detail)) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"无法连接分析 API（{self.base_url}）。请确认 FastAPI 服务已启动。原始错误：{exc}"
            ) from exc

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def examples(self) -> dict[str, Any]:
        return self._request("GET", "/examples")

    def schema(self) -> dict[str, Any]:
        return self._request("GET", "/schema")

    def query(self, question: str) -> dict[str, Any]:
        return self._request("POST", "/query", json={"question": question})

