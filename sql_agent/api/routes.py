from fastapi import APIRouter, HTTPException, Request, status

from sql_agent.agent.graph import AnalyticsAgent
from sql_agent.agent.schema_catalog import SchemaCatalog
from sql_agent.agent.state import AgentResult
from sql_agent.api.schemas import (
    ExampleQuestion,
    ExamplesResponse,
    HealthResponse,
    QueryRequest,
    SchemaResponse,
)
from sql_agent.core.exceptions import AgentQueryError, LLMProviderError

router = APIRouter()


def get_agent(request: Request) -> AnalyticsAgent:
    return request.app.state.agent


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    try:
        database_ok = await request.app.state.executor.healthcheck()
    except Exception:
        database_ok = False
    return HealthResponse(
        status="ok" if database_ok else "degraded",
        database=database_ok,
        dialect=settings.sql_dialect,
        llm_provider=settings.llm_provider,
        llm_model=settings.resolved_llm_model,
        tables=list(settings.allowed_table_names),
        seed=request.app.state.seed_stats,
    )


@router.get("/schema", response_model=SchemaResponse)
async def schema(request: Request) -> SchemaResponse:
    catalog: SchemaCatalog = request.app.state.catalog
    settings = request.app.state.settings
    return SchemaResponse(
        dialect=settings.sql_dialect,
        allowed_tables=list(settings.allowed_table_names),
        tables=[table.model_dump() for table in catalog.list_tables()],
    )


@router.get("/examples", response_model=ExamplesResponse)
async def examples() -> ExamplesResponse:
    return ExamplesResponse(
        examples=[
            ExampleQuestion(category="趋势", question="最近 7 天每天新增用户数是多少"),
            ExampleQuestion(category="排名", question="上个月销售额最高的前 10 个产品是什么"),
            ExampleQuestion(category="分布", question="各订单状态的订单数量占比是多少"),
            ExampleQuestion(category="渠道", question="各销售渠道的销售额分布如何"),
            ExampleQuestion(category="地域", question="不同城市的用户数量是多少"),
        ]
    )


@router.post("/query", response_model=AgentResult)
async def query(payload: QueryRequest, request: Request) -> AgentResult:
    agent = get_agent(request)
    try:
        return await agent.run(payload.question)
    except AgentQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": exc.message, "detail": exc.detail},
        ) from exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": exc.code, "message": exc.message, "detail": exc.detail},
        ) from exc

