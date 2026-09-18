from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sql_agent.agent.graph import AnalyticsAgent
from sql_agent.agent.schema_catalog import SchemaCatalog
from sql_agent.api.routes import router
from sql_agent.core.config import get_settings
from sql_agent.core.exceptions import AppError
from sql_agent.core.logging import configure_logging
from sql_agent.db.session import get_engine, init_database
from sql_agent.llm.factory import create_llm
from sql_agent.security.sql_guard import SQLGuard
from sql_agent.services.executor import ReadOnlyQueryExecutor


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.debug)

    seed_stats = init_database(settings)
    engine = get_engine()
    catalog = SchemaCatalog(engine, settings.allowed_table_names)
    executor = ReadOnlyQueryExecutor(
        database_url=settings.effective_readonly_database_url,
        dialect=settings.sql_dialect,
        timeout_seconds=settings.sql_timeout_seconds,
        max_rows=settings.sql_max_rows,
    )
    llm = create_llm(settings)
    guard = SQLGuard(
        allowed_tables=settings.allowed_table_names,
        max_rows=settings.sql_max_rows,
        max_length=settings.sql_max_length,
    )
    agent = AnalyticsAgent(
        catalog=catalog,
        llm=llm,
        guard=guard,
        executor=executor,
        dialect=settings.sql_dialect,
        max_rows=settings.sql_max_rows,
        max_retries=settings.sql_max_retries,
    )

    app.state.settings = settings
    app.state.seed_stats = seed_stats
    app.state.catalog = catalog
    app.state.executor = executor
    app.state.agent = agent

    try:
        yield
    finally:
        executor.dispose()


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="自然语言 -> 安全 SQL -> 只读执行 -> 图表 -> 数据总结",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=settings.cors_origin_list != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix=settings.api_prefix)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": f"{settings.api_prefix}/health",
    }


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"code": exc.code, "message": exc.message, "detail": exc.detail},
    )


def run() -> None:
    resolved = get_settings()
    uvicorn.run(
        "sql_agent.main:app",
        host=resolved.api_host,
        port=resolved.api_port,
        reload=resolved.debug,
    )


if __name__ == "__main__":
    run()

