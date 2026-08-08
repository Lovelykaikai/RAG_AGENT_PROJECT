from __future__ import annotations

import os
from types import TracebackType

from dotenv import load_dotenv
from langgraph.checkpoint.mysql.pymysql import PyMySQLSaver

from utils.logger_handler import logger
from utils.path_tool import get_abs_path


class MySQLCheckpointer:
    """Own the MySQL checkpointer context and initialize its tables once."""

    def __init__(self, connection_uri: str | None = None):
        load_dotenv(get_abs_path(".env"))
        self.connection_uri = connection_uri or os.getenv("CHECKPOINT_DB_URI")
        if not self.connection_uri:
            raise RuntimeError(
                "Missing CHECKPOINT_DB_URI. Set it in .env, for example: "
                "mysql://root:password@127.0.0.1:3306/local_host?charset=utf8mb4"
            )

        self._context_manager = None
        self.saver: PyMySQLSaver | None = None

    def start(self) -> PyMySQLSaver:
        """Open the saver and create LangGraph tables if they do not exist."""
        if self.saver is not None:
            return self.saver

        self._context_manager = PyMySQLSaver.from_conn_string(self.connection_uri)
        try:
            self.saver = self._context_manager.__enter__()
            self.saver.setup()
            logger.info("[MySQLCheckpointer] checkpointer initialized")
            return self.saver
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        """Close the underlying connection context when the application stops."""
        if self._context_manager is not None:
            self._context_manager.__exit__(None, None, None)
        self._context_manager = None
        self.saver = None

    def __enter__(self) -> PyMySQLSaver:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._context_manager is not None:
            self._context_manager.__exit__(exc_type, exc_value, traceback)
        self._context_manager = None
        self.saver = None
