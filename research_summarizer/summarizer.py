"""LLM layer: turns collected evidence into a raw model response.

This module owns the LLM client configuration and the single LLM call.
It does not acquire evidence or parse/validate the model output.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from research_summarizer.models import SummaryResult
from research_summarizer.prompts import SUMMARIZE_SYSTEM_PROMPT


def build_model(timeout: int = 120) -> ChatOpenAI:
    """Build the configured LLM client, or raise if configuration is missing."""
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    model = os.getenv("OPENAI_MODEL")

    if not all([api_key, base_url, model]):
        raise ValueError(
            "Missing API configuration. Set OPENAI_API_KEY, OPENAI_BASE_URL, "
            "and OPENAI_MODEL in your environment variables."
        )

    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout,
    )


def _response_format() -> dict:
    """Request the configured output format without automatic retry or downgrade."""
    mode = os.getenv("OPENAI_OUTPUT_FORMAT", "json_object").strip().lower()
    if mode == "json_object":
        return {"type": "json_object"}
    if mode != "json_schema":
        raise ValueError("OPENAI_OUTPUT_FORMAT must be json_schema or json_object.")

    schema = SummaryResult.model_json_schema()

    def make_strict(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in node.values():
                make_strict(value)
        elif isinstance(node, list):
            for value in node:
                make_strict(value)

    make_strict(schema)
    return {
        "type": "json_schema",
        "json_schema": {"name": "SummaryResult", "strict": True, "schema": schema},
    }


def summarize_evidence(request: str, evidence: str, model: ChatOpenAI) -> str:
    """Make one synthesis call; leave parsing and citation validation to Python.

    Unsupported schema requests fail explicitly, without a second synthesis call.
    """
    messages = [
        SystemMessage(content=SUMMARIZE_SYSTEM_PROMPT),
        HumanMessage(content=f"Request: {request}\n\nEvidence:\n{evidence}"),
    ]
    response = model.bind(response_format=_response_format()).invoke(messages)
    return getattr(response, "content", str(response))
