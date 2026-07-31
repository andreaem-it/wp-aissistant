import json

import pytest

from evals.rag_eval import EvalCase, load_cases, retrieval_hit, score_case, summarize


def test_load_cases_validates_and_normalizes(tmp_path):
    dataset = tmp_path / "eval.jsonl"
    dataset.write_text(json.dumps({
        "id": "shipping",
        "query": "Quando spedite?",
        "expected_outcome": "answer",
        "required_terms": ["GIORNI"],
    }) + "\n", encoding="utf-8")
    case = load_cases(dataset)[0]
    assert case.id == "shipping"
    assert case.required_terms == ("giorni",)


def test_load_cases_rejects_duplicate_ids(tmp_path):
    dataset = tmp_path / "eval.jsonl"
    row = json.dumps({"id": "same", "query": "x", "expected_outcome": "answer"})
    dataset.write_text(f"{row}\n{row}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicato"):
        load_cases(dataset)


def test_retrieval_hit_uses_only_selected_sources():
    meta = [
        {"source_ref": "https://shop.test/spedizioni", "selected": True},
        {"source_ref": "https://shop.test/resi", "selected": False},
    ]
    assert retrieval_hit(meta, ["spedizioni"]) is True
    assert retrieval_hit(meta, ["resi"]) is False
    assert retrieval_hit(meta, []) is None


def test_score_and_summary_require_outcome_retrieval_and_terms():
    case = EvalCase(
        id="shipping",
        query="Quando spedite?",
        expected_outcome="answer",
        relevant_sources=("spedizioni",),
        required_terms=("3 giorni",),
        forbidden_terms=("forse",),
    )
    passed = score_case(case, outcome="answer", text="Spediamo in 3 giorni.", hit=True)
    failed = score_case(case, outcome="answer", text="Forse domani.", hit=True)
    assert passed["passed"] is True
    assert failed["passed"] is False
    assert summarize([passed, failed]) == {
        "cases": 2,
        "passed": 1,
        "pass_rate": 0.5,
        "outcome_accuracy": 1.0,
        "retrieval_recall": 1.0,
    }
