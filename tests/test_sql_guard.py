import pytest

from sql_agent.core.exceptions import SQLSafetyError
from sql_agent.security.sql_guard import SQLGuard


@pytest.fixture()
def guard() -> SQLGuard:
    return SQLGuard(allowed_tables=("users", "orders", "products"), max_rows=5)


def test_select_gets_limit(guard: SQLGuard) -> None:
    result = guard.validate("SELECT id, name FROM users ORDER BY id", dialect="sqlite")
    assert result.tables == ["users"]
    assert "LIMIT 5" in result.sql.upper()


def test_cte_is_allowed(guard: SQLGuard) -> None:
    sql = """
    WITH recent_orders AS (
        SELECT id, user_id FROM orders WHERE status = 'paid'
    )
    SELECT u.id, u.name FROM users u
    JOIN recent_orders r ON r.user_id = u.id
    """
    result = guard.validate(sql, dialect="sqlite")
    assert set(result.tables) == {"users", "orders"}


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM users",
        "UPDATE users SET status = 'banned'",
        "SELECT * FROM users; DROP TABLE users",
        "SELECT * FROM sqlite_master",
        "SELECT pg_sleep(10)",
    ],
)
def test_dangerous_sql_is_rejected(guard: SQLGuard, sql: str) -> None:
    with pytest.raises(SQLSafetyError):
        guard.validate(sql, dialect="sqlite")


def test_existing_lower_limit_is_preserved(guard: SQLGuard) -> None:
    result = guard.validate("SELECT id FROM users ORDER BY id LIMIT 3", dialect="sqlite")
    assert result.applied_limit == 3
    assert "LIMIT 3" in result.sql.upper()


def test_large_limit_is_capped(guard: SQLGuard) -> None:
    result = guard.validate("SELECT id FROM users LIMIT 100", dialect="sqlite")
    assert result.applied_limit == 5
    assert "LIMIT 5" in result.sql.upper()
    assert result.warnings

