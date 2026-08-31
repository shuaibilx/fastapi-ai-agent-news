import asyncio
import json
from types import SimpleNamespace

from sqlalchemy.dialects import mysql
from sqlalchemy.exc import OperationalError
from starlette.requests import Request

from app.core.exceptions import sqlalchemy_error_handler
from app.services.history import delete_history


class CapturingSession:
    def __init__(self, rowcount: int):
        self.rowcount = rowcount
        self.statement = None
        self.committed = False

    async def execute(self, statement):
        self.statement = statement
        return SimpleNamespace(rowcount=self.rowcount)

    async def commit(self):
        self.committed = True


def test_delete_history_targets_the_unique_history_record_not_every_view_of_the_same_news():
    """Changing History.id back to History.news_id would delete unrelated view records."""
    session = CapturingSession(rowcount=1)

    deleted = asyncio.run(delete_history(session, user_id=42, history_id=99))

    compiled = str(session.statement.compile(
        dialect=mysql.dialect(),
        compile_kwargs={"literal_binds": True},
    ))
    assert deleted is True
    assert session.committed is True
    assert "history.user_id = 42" in compiled
    assert "history.id = 99" in compiled
    assert "history.news_id = 99" not in compiled


def test_database_failures_do_not_expose_tracebacks_or_connection_secrets_to_clients():
    """Re-enabling debug payloads would leak database internals to browser callers."""
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/api/news/list",
        "headers": [],
        "scheme": "http",
        "server": ("127.0.0.1", 8000),
    })
    error = OperationalError(
        "SELECT 1",
        {},
        Exception("mysql://root:secret@localhost/news_app"),
    )

    response = asyncio.run(sqlalchemy_error_handler(request, error))

    payload = json.loads(response.body)
    assert response.status_code == 500
    assert payload == {
        "code": 500,
        "message": "数据库操作失败，请稍后重试",
        "data": None,
    }
