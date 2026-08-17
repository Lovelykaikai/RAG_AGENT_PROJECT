import unittest
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessageChunk, ToolMessage

from agent.react_agent import ReactAgent
from agent.tools.agent_tools import get_city_transport


class _FakeGraph:
    def stream(self, *_args, **_kwargs):
        yield "messages", (AIMessageChunk(content="最终回答"), {})
        yield "messages", (ToolMessage(content="参考资料不足，无法完整总结。", tool_call_id="call-1"), {})


class AgentStreamingTests(unittest.TestCase):
    def test_execute_stream_does_not_forward_tool_message_content(self):
        agent = object.__new__(ReactAgent)
        agent.agent = _FakeGraph()

        events = list(agent.execute_stream("测试", "thread-test"))

        self.assertEqual(events, [{"type": "message", "content": "最终回答"}])

    def test_city_transport_preserves_city_filter_for_rag(self):
        service = Mock()
        service.rag_summarize.return_value = "杭州交通资料"

        with patch("agent.tools.agent_tools._get_rag_service", return_value=service):
            result = get_city_transport.invoke({"city": "杭州"})

        self.assertEqual(result, "杭州交通资料")
        service.rag_summarize.assert_called_once_with(
            "杭州 市内交通 地铁 机场 火车站 景点 出行建议",
            "杭州",
        )


if __name__ == "__main__":
    unittest.main()
