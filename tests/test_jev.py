"""Unit tests for Jev evidence selection. TypeSafe is always mocked."""

from types import SimpleNamespace

from typesafe_sdk import TypeSafeAPIConnectionError

from research_summarizer.evidence import EvidenceItem, EvidenceResult
from research_summarizer.jev import (
    DEFAULT_TYPESAFE_MODEL,
    MAX_SELECTED_SOURCES,
    NO_RELEVANT_EVIDENCE_NOTE,
    SourceJudgment,
    _redact_client,
    judge_evidence,
    select_survivors,
)


def _item(index: int) -> EvidenceItem:
    return EvidenceItem(
        id=f"S{index}",
        title=f"Source {index}",
        url=f"https://example.com/{index}",
        content=f"Body {index}.",
    )


def _judgment(
    index: int,
    relevant: float,
    usable: float = 0.9,
    injection: float = 0.0,
) -> SourceJudgment:
    return SourceJudgment(
        item=_item(index),
        relevant=relevant,
        usable_evidence=usable,
        prompt_injection=injection,
    )


class _FakeClient:
    """Minimal stand-in for TypeSafeClient.system_one."""

    def __init__(self, answers_by_title, error=None):
        self.calls = []
        self._answers_by_title = answers_by_title
        self._error = error

    def system_one(self, state, questions, model=None):
        self.calls.append({"state": state, "questions": questions, "model": model})
        if self._error is not None:
            raise self._error
        relevant, usable, injection = self._answers_by_title[state["source"]["title"]]
        return SimpleNamespace(
            answers={
                "relevant": SimpleNamespace(noul=relevant),
                "usable_evidence": SimpleNamespace(noul=usable),
                "prompt_injection": SimpleNamespace(noul=injection),
            }
        )


# ---------------------------------------------------------------------------
# select_survivors (pure policy)
# ---------------------------------------------------------------------------


def test_select_ranks_by_relevance_and_keeps_top_three():
    judgments = [_judgment(index, relevant=0.9 - index * 0.1) for index in range(5)]

    survivors = select_survivors(judgments)

    assert [judgment.item.id for judgment in survivors] == ["S0", "S1", "S2"]
    assert len(survivors) == MAX_SELECTED_SOURCES


def test_select_drops_low_relevance():
    assert select_survivors([_judgment(0, relevant=0.2)]) == []


def test_select_drops_low_usable_evidence():
    assert select_survivors([_judgment(0, relevant=0.9, usable=0.1)]) == []


def test_select_drops_prompt_injection_first():
    judgments = [_judgment(0, relevant=0.99, usable=0.99, injection=0.95)]

    assert select_survivors(judgments) == []


def test_select_thresholds_and_limit_are_configurable():
    judgment = _judgment(0, relevant=0.5, usable=0.5)
    assert select_survivors([judgment]) == []

    relaxed = {"injection_max": 0.9, "relevant_min": 0.4, "evidence_min": 0.4}
    assert select_survivors([judgment], thresholds=relaxed) == [judgment]
    assert select_survivors([judgment], thresholds=relaxed, limit=0) == []


# ---------------------------------------------------------------------------
# tracing redaction
# ---------------------------------------------------------------------------


def test_redact_client_removes_only_client():
    inputs = {"request": "q", "items": (), "client": object(), "model": "jev-latest"}

    redacted = _redact_client(inputs)

    assert "client" not in redacted
    assert redacted["request"] == "q"
    assert redacted["model"] == "jev-latest"


# ---------------------------------------------------------------------------
# judge_evidence (client mocked)
# ---------------------------------------------------------------------------


def test_judge_makes_one_request_per_source_with_contract_only_state():
    items = (_item(1), _item(2))
    client = _FakeClient(
        {"Source 1": (0.9, 0.8, 0.0), "Source 2": (0.2, 0.2, 0.0)}
    )

    result = judge_evidence("latest AI news", items, client=client, model="jev-test")

    assert isinstance(result, EvidenceResult)
    assert [item.id for item in result.items] == ["S1"]
    assert len(client.calls) == 2

    first = client.calls[0]
    assert first["model"] == "jev-test"
    assert first["state"]["request"] == "latest AI news"
    assert set(first["state"]["source"]) == {"title", "url", "content"}
    assert first["state"]["source"]["content"] == "Body 1."
    assert set(first["questions"]) == {"relevant", "usable_evidence", "prompt_injection"}


def test_judge_ranks_and_caps_selected_sources():
    items = tuple(_item(index) for index in range(1, 6))
    client = _FakeClient(
        {f"Source {index}": (0.9 - index * 0.05, 0.9, 0.0) for index in range(1, 6)}
    )

    result = judge_evidence("q", items, client=client)

    assert [item.id for item in result.items] == ["S1", "S2", "S3"]


def test_judge_drops_injected_source():
    items = (_item(1), _item(2))
    client = _FakeClient(
        {"Source 1": (0.9, 0.9, 0.99), "Source 2": (0.9, 0.9, 0.0)}
    )

    result = judge_evidence("q", items, client=client)

    assert [item.id for item in result.items] == ["S2"]


def test_judge_returns_note_when_nothing_survives():
    client = _FakeClient({"Source 1": (0.1, 0.1, 0.0)})

    result = judge_evidence("q", (_item(1),), client=client)

    assert result.items == ()
    assert result.note == NO_RELEVANT_EVIDENCE_NOTE


def test_judge_falls_back_to_all_items_on_service_error():
    items = (_item(1), _item(2))
    client = _FakeClient({}, error=TypeSafeAPIConnectionError("connection reset"))

    result = judge_evidence("q", items, client=client)

    assert result.items == items
    assert result.note == ""


def test_judge_falls_back_when_api_key_missing(mocker, no_typesafe_key):
    mock_load = mocker.patch("research_summarizer.jev.load_dotenv")
    items = (_item(1),)

    result = judge_evidence("q", items)

    assert result.items == items
    mock_load.assert_called_once()


def test_judge_skips_network_for_empty_items(mocker):
    mock_build = mocker.patch("research_summarizer.jev.build_client")

    result = judge_evidence("q", ())

    assert result.items == ()
    mock_build.assert_not_called()


def test_judge_uses_configured_model(mocker):
    mocker.patch("research_summarizer.jev.load_dotenv")
    mocker.patch.dict("os.environ", {"TYPESAFE_MODEL": "jev-custom"})
    client = _FakeClient({"Source 1": (0.9, 0.9, 0.0)})

    judge_evidence("q", (_item(1),), client=client)

    assert client.calls[0]["model"] == "jev-custom"


def test_judge_defaults_to_jev_latest(mocker, no_typesafe_key):
    mocker.patch("research_summarizer.jev.load_dotenv")
    client = _FakeClient({"Source 1": (0.9, 0.9, 0.0)})

    judge_evidence("q", (_item(1),), client=client)

    assert client.calls[0]["model"] == DEFAULT_TYPESAFE_MODEL
    assert DEFAULT_TYPESAFE_MODEL == "jev-latest"
