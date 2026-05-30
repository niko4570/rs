"""Helpers for testing the LangChain agent with mocked LLM responses."""

from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI


def make_tool_call_msg(tool_name: str, args: dict, call_id: str = "call_1") -> AIMessage:
    """Create an AIMessage that instructs the agent to call a tool."""
    return AIMessage(
        content="",
        tool_calls=[{
            "name": tool_name,
            "args": args,
            "id": call_id,
            "type": "tool_call",
        }],
    )


def make_final_msg(content: str) -> AIMessage:
    """Create an AIMessage representing the agent's final answer."""
    return AIMessage(content=content)


def mock_agent_llm(responses: list[AIMessage]):
    """Context manager that patches ChatOpenAI.invoke to return the given
    responses in sequence. Use in a `with` block.
    """
    it = iter(responses)
    return patch.object(
        ChatOpenAI, "invoke",
        lambda self, input, *args, **kwargs: next(it),
    )
