"""Output constraints keep synthesis to one call and Python-owned validation."""
from unittest.mock import Mock

import pytest

from research_summarizer.models import SynthesisResult
from research_summarizer.parser import parse_synthesis
from research_summarizer.summarizer import _response_format, summarize_evidence


def test_schema_requires_all_fields_and_forbids_unknown_properties(monkeypatch):
    monkeypatch.setenv("OPENAI_OUTPUT_FORMAT", "json_schema")
    fmt = _response_format()
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    schema = fmt["json_schema"]["schema"]
    assert set(schema["required"]) == set(SynthesisResult.model_fields)
    for node in [schema, *schema["$defs"].values()]:
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])
        assert all("default" not in prop for prop in node["properties"].values())


def test_single_call_returns_raw_output_for_parser(monkeypatch):
    monkeypatch.setenv("OPENAI_OUTPUT_FORMAT", "json_schema")
    result = SynthesisResult(summary_bullets=["a", "b", "c", "d"],
                           key_details="No evidence.", citations=[], caveats=["Unavailable"])
    raw = result.model_dump_json()
    model = Mock()
    model.bind.return_value.invoke.return_value = Mock(content=raw)
    answer = summarize_evidence("question", "No evidence.", model)
    assert parse_synthesis(answer, {}).summary_bullets == result.summary_bullets
    model.bind.assert_called_once_with(response_format=_response_format())
    model.bind.return_value.invoke.assert_called_once()


def test_unsupported_schema_does_not_retry_or_downgrade(monkeypatch):
    monkeypatch.setenv("OPENAI_OUTPUT_FORMAT", "json_schema")
    model = Mock()
    model.bind.return_value.invoke.side_effect = RuntimeError("Unsupported json_schema")
    with pytest.raises(RuntimeError, match="Unsupported"):
        summarize_evidence("question", "evidence", model)
    model.bind.assert_called_once()
    model.bind.return_value.invoke.assert_called_once()


def test_explicit_json_mode_compatibility(monkeypatch):
    monkeypatch.setenv("OPENAI_OUTPUT_FORMAT", "json_object")
    assert _response_format() == {"type": "json_object"}


def test_invalid_format_fails_before_call(monkeypatch):
    monkeypatch.setenv("OPENAI_OUTPUT_FORMAT", "typo")
    model = Mock()
    with pytest.raises(ValueError, match="OPENAI_OUTPUT_FORMAT"):
        summarize_evidence("q", "e", model)
    model.bind.assert_not_called()


def test_default_retains_compatible_json_mode(monkeypatch):
    monkeypatch.delenv("OPENAI_OUTPUT_FORMAT", raising=False)
    assert _response_format() == {"type": "json_object"}
