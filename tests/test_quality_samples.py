"""Replay checks use the real production parser and a fake synthesis transport."""

import json
from unittest.mock import Mock

import pytest

from evaluation.run import load_cases, prepare, replay


@pytest.mark.parametrize("case", load_cases(), ids=lambda case: case["id"])
def test_frozen_evidence_has_consistent_source_contract(case):
    text, urls, citations = prepare(case)
    assert text.strip()
    assert urls == {url for url in citations if url is not None}
    if case["route"] == "file":
        assert urls == set()
        assert set(citations) == {None}
    if not case["items"]:
        assert citations == {} and urls == set()


def test_replay_preserves_invalid_raw_and_calls_synthesis_once():
    model = Mock()
    model.bind.return_value.invoke.return_value = Mock(content='{"broken": true}')
    row = replay(load_cases()[0], model)
    assert row["status"] == "invalid"
    assert row["raw"] == '{"broken": true}'
    assert row["result"] is None
    model.bind.return_value.invoke.assert_called_once()


def test_replay_does_not_confuse_mechanical_validity_with_semantic_review():
    case = load_cases()[0]
    payload = {
        "summary_bullets": ["Unsupported assertion"] * 4,
        "key_details": "Needs human review", "caveats": [],
        "citations": [{"bullet_index": i, "source_id": "S1",
                    "excerpt": "Cedar pilot ran for four weeks"} for i in range(4)],
    }
    model = Mock()
    model.bind.return_value.invoke.return_value = Mock(content=json.dumps(payload))
    row = replay(case, model)
    assert row["status"] == "valid"
    assert row["review"]["support"] is None
    model.bind.return_value.invoke.assert_called_once()


def test_replay_redacts_provider_error_and_continues_without_retry():
    model = Mock()
    model.bind.return_value.invoke.side_effect = RuntimeError("secret credential")
    row = replay(load_cases()[0], model)
    assert row["status"] == "call_error"
    assert row["error"] == "RuntimeError"
    assert "secret" not in json.dumps(row)
    model.bind.return_value.invoke.assert_called_once()
