from __future__ import annotations

import asyncio
import base64
import time
from datetime import date, datetime
from datetime import time as datetime_time
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Engine, create_engine, event

from sql_agent.core.exceptions import SQLExecutionError
from sql_agent.db.session import ensure_sqlite_parent


class QueryResult(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    execution_ms: int


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, datetime_time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    return str(value)


class ReadOnlyQueryExecutor:
    def __init__(
        self,
        *,
        database_url: str,
        dialect: str,
        timeout_seconds: int = 10,
        max_rows: int = 200,
    ) -> None:
        self.database_url = database_url
        self.dialect = dialect
        self.timeout_seconds = timeout_seconds
        self.max_rows = max_rows
        ensure_sqlite_parent(database_url)
        connect_args = {"check_same_thread": False} if dialect == "sqlite" else {}
        self.engine: Engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_recycle=1_800,
            connect_args=connect_args,
        )
        self._install_read_only_guard()

    def _install_read_only_guard(self) -> None:
        @event.listens_for(self.engine, "connect")
        def _configure_connection(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            try:
                if self.dialect == "sqlite":
                    cursor.execute("PRAGMA query_only=ON")
                    cursor.execute("PRAGMA foreign_keys=ON")
                elif self.dialect == "postgresql":
                    cursor.execute("SET default_transaction_read_only = on")
                elif self.dialect == "mysql":
                    cursor.execute("SET SESSION TRANSACTION READ ONLY")
            finally:
                cursor.close()

    def _apply_database_timeout(self, connection) -> None:  # noqa: ANN001
        milliseconds = max(self.timeout_seconds * 1_000, 1_000)
        try:
            if self.dialect == "postgresql":
                connection.exec_driver_sql(f"SET LOCAL statement_timeout = {milliseconds}")
            elif self.dialect == "mysql":
                connection.exec_driver_sql(f"SET SESSION MAX_EXECUTION_TIME = {milliseconds}")
        except Exception:
            pass

    def _execute_sync(self, sql: str) -> QueryResult:
        started = time.perf_counter()
        try:
            with self.engine.connect() as connection:
                self._apply_database_timeout(connection)
                result = connection.exec_driver_sql(sql)
                if result.returns_rows is False:
                    raise SQLExecutionError("查询没有返回结果集。")
                columns = [str(column) for column in result.keys()]
                raw_rows = result.fetchmany(self.max_rows + 1)
                truncated = len(raw_rows) > self.max_rows
                if truncated:
                    raw_rows = raw_rows[: self.max_rows]
                rows = [[jsonable(value) for value in row] for row in raw_rows]
        except SQLExecutionError:
            raise
        except Exception as exc:
            raise SQLExecutionError(f"SQL 执行失败：{exc}") from exc

        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            execution_ms=int((time.perf_counter() - started) * 1_000),
        )

    async def execute(self, sql: str) -> QueryResult:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._execute_sync, sql),
                timeout=self.timeout_seconds + 1,
            )
        except TimeoutError as exc:
            raise SQLExecutionError(
                f"SQL 执行超过 {self.timeout_seconds} 秒，已终止等待。"
            ) from exc

    async def healthcheck(self) -> bool:
        result = await self.execute("SELECT 1 AS healthcheck")
        return result.rows == [[1]]

    def dispose(self) -> None:
        self.engine.dispose()

