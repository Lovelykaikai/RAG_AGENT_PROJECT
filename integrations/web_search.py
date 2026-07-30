"""Tavily-backed web search integration for time-sensitive travel information."""

from __future__ import annotations

import logging
import os
from threading import Lock
from typing import Any

from dotenv import load_dotenv
from tavily import TavilyClient


load_dotenv()

logger = logging.getLogger(__name__)

SEARCH_UNAVAILABLE_MESSAGE = "当前联网搜索暂时不可用，请基于已有资料提供保守建议。"


class WebSearchService:
    """Search the public web and turn results into model-friendly text."""

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.getenv("TAVILY_API_KEY")
        self._client = TavilyClient(api_key=self._api_key) if self._api_key else None

    def search(self, query: str, max_results: int = 5) -> str:
        """Return concise search results, or a conservative fallback on failure."""
        normalized_query = query.strip()
        if not normalized_query:
            return "请提供需要搜索的具体问题或关键词。"

        if self._client is None:
            logger.warning("[web_search]TAVILY_API_KEY未配置")
            return SEARCH_UNAVAILABLE_MESSAGE

        try:
            response = self._client.search(
                query=normalized_query,
                search_depth="basic",
                max_results=max(1, min(max_results, 10)),
                include_answer=False,
                include_raw_content=False,
            )
        except Exception as exc:
            logger.warning("[web_search]Tavily请求失败: %s", type(exc).__name__)
            return SEARCH_UNAVAILABLE_MESSAGE

        results = response.get("results", []) if isinstance(response, dict) else []
        if not results:
            return f"没有搜索到与“{normalized_query}”相关的可靠网页结果。"

        return self._format_results(normalized_query, results)

    @staticmethod
    def _format_results(query: str, results: list[dict[str, Any]]) -> str:
        lines = ["联网搜索结果：", f"查询：{query}"]
        for index, result in enumerate(results, start=1):
            title = str(result.get("title") or "无标题").strip()
            url = str(result.get("url") or "").strip()
            content = str(result.get("content") or "暂无摘要").strip()
            lines.extend(
                [
                    "",
                    f"[来源 {index}]",
                    f"标题：{title}",
                    f"链接：{url or '暂无链接'}",
                    f"摘要：{content}",
                ]
            )
        return "\n".join(lines)


_service_lock = Lock()
_service: WebSearchService | None = None


def get_web_search_service() -> WebSearchService:
    """Return the process-wide search service instance."""
    global _service

    if _service is not None:
        return _service

    with _service_lock:
        if _service is None:
            _service = WebSearchService()
        return _service

