from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from urllib.parse import parse_qs, unquote, urlsplit

import pymysql
from dotenv import load_dotenv

from utils.path_tool import get_abs_path


# 新建或重置会话时使用的默认标题。routers.py 依赖它判断是否要用首条消息覆盖标题，
# 修改时两边会同步，不要在其他地方硬编码这个字符串。
DEFAULT_SESSION_TITLE = "新的行程"


class MySQLSessionStore:
    """Store session metadata separately from LangGraph checkpoint messages."""

    def __init__(self, connection_uri: str | None = None):
        load_dotenv(get_abs_path(".env"))
        self.connection_uri = connection_uri or os.getenv("CHECKPOINT_DB_URI")
        if not self.connection_uri:
            raise RuntimeError("Missing CHECKPOINT_DB_URI for session metadata storage")
        self.connection_options = self._parse_connection_uri(self.connection_uri)

    @staticmethod
    def _parse_connection_uri(connection_uri: str) -> dict[str, Any]:
        parsed = urlsplit(connection_uri)
        if parsed.scheme != "mysql" or not parsed.hostname or not parsed.path.strip("/"):
            raise ValueError("CHECKPOINT_DB_URI must use mysql://user:password@host:port/database")

        query = parse_qs(parsed.query)
        return {
            "host": parsed.hostname,
            "port": parsed.port or 3306,
            "user": unquote(parsed.username or ""),
            "password": unquote(parsed.password or ""),
            "database": parsed.path.strip("/"),
            "charset": query.get("charset", ["utf8mb4"])[0],
            "autocommit": True,
            "connect_timeout": 5,
        }

    @contextmanager
    def _connection(self) -> Iterator[pymysql.connections.Connection]:
        connection = pymysql.connect(**self.connection_options)
        try:
            yield connection
        finally:
            connection.close()

    def setup(self) -> None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chat_sessions (
                        thread_id VARCHAR(128) NOT NULL,
                        title VARCHAR(255) NOT NULL,
                        created_at DATETIME(6) NOT NULL,
                        updated_at DATETIME(6) NOT NULL,
                        PRIMARY KEY (thread_id),
                        INDEX idx_chat_sessions_updated_at (updated_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )

    def create(self, thread_id: str, title: str = DEFAULT_SESSION_TITLE) -> dict[str, Any]:
        now = self._now()
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO chat_sessions (thread_id, title, created_at, updated_at)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE updated_at = VALUES(updated_at)
                    """,
                    (thread_id, title, now, now),
                )
        return self.get(thread_id)  # type: ignore[return-value]

    def list(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT thread_id, title, created_at, updated_at
                    FROM chat_sessions
                    ORDER BY updated_at DESC
                    """
                )
                return list(cursor.fetchall())

    def get(self, thread_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT thread_id, title, created_at, updated_at
                    FROM chat_sessions
                    WHERE thread_id = %s
                    """,
                    (thread_id,),
                )
                return cursor.fetchone()

    def touch(self, thread_id: str) -> None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE chat_sessions SET updated_at = %s WHERE thread_id = %s",
                    (self._now(), thread_id),
                )

    def rename(self, thread_id: str, title: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE chat_sessions
                    SET title = %s, updated_at = %s
                    WHERE thread_id = %s
                    """,
                    (title, self._now(), thread_id),
                )
        return self.get(thread_id)

    def reset(self, thread_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE chat_sessions
                    SET title = %s, updated_at = %s
                    WHERE thread_id = %s
                    """,
                    (DEFAULT_SESSION_TITLE, self._now(), thread_id),
                )
        return self.get(thread_id)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)
