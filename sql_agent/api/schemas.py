from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class HealthResponse(BaseModel):
    status: str
    database: bool
    dialect: str
    llm_provider: str
    llm_model: str
    tables: list[str]
    seed: dict[str, int | str] | None = None


class SchemaResponse(BaseModel):
    dialect: str
    allowed_tables: list[str]
    tables: list[object]


class ExampleQuestion(BaseModel):
    category: str
    question: str


class ExamplesResponse(BaseModel):
    examples: list[ExampleQuestion]


