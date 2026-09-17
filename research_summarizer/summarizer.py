"""LLM layer: turns collected evidence into a raw model response.

This module owns the LLM client configuration and the single LLM call.
It does not acquire evidence or parse/validate the model output.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from research_summarizer.prompts import SUMMARIZE_SYSTEM_PROMPT


def build_model(timeout: int = 120) -> ChatOpenAI:
    """Build the configured LLM client, or raise if configuration is missing."""
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    model = os.getenv("OPENAI_MODEL")

    if not all([api_key, base_url, model]):
        raise ValueError(
            "Missing API configuration. Set OPENAI_API_KEY, OPENAI_BASE_URL, and OPENAI_MODEL in your environment variables."
        )

    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout,
        extra_body={
            "thinking": {
                "type": "disabled",
            }
        }
    )


def summarize_evidence(request: str, evidence: str, model: ChatOpenAI) -> str:
    """Make a single LLM call and return the raw model output.

    Parsing and validation happen in ``parser.parse_summary``.
    """
    messages = [
        SystemMessage(content=SUMMARIZE_SYSTEM_PROMPT),
        HumanMessage(content=f"Request: {request}\n\nEvidence:\n{evidence}"),
    ]
    response = model.invoke(messages)
    return getattr(response, "content", str(response))
