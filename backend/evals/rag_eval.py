"""Evaluate retrieval and answer routing against a tenant-specific JSONL dataset.

The command uses the same database, embedding provider, thresholds and prompt path as the
production application. It is read-only: no conversations, messages or tickets are created.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from sqlmodel import Session

from app.db import engine
from app.llm import LLMUnavailableError, chat
from app.main import _build_system, _is_small_talk, _retrieval_is_in_scope
from app.rag import retrieve_with_meta


ALLOWED_OUTCOMES = {"answer", "out_of_scope", "escalate"}


@dataclass(frozen=True)
class EvalCase:
    id: str
    query: str
    expected_outcome: str
    relevant_sources: tuple[str, ...] = ()
    required_terms: tuple[str, ...] = ()
    forbidden_terms: tuple[str, ...] = ()


def load_cases(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: JSON non valido: {exc.msg}") from exc
        missing = {"id", "query", "expected_outcome"} - row.keys()
        if missing:
            raise ValueError(f"{path}:{line_number}: campi mancanti: {', '.join(sorted(missing))}")
        if row["id"] in seen:
            raise ValueError(f"{path}:{line_number}: id duplicato: {row['id']}")
        if row["expected_outcome"] not in ALLOWED_OUTCOMES:
            raise ValueError(
                f"{path}:{line_number}: expected_outcome deve essere uno di "
                f"{', '.join(sorted(ALLOWED_OUTCOMES))}"
            )
        seen.add(row["id"])
        cases.append(EvalCase(
            id=str(row["id"]),
            query=str(row["query"]),
            expected_outcome=row["expected_outcome"],
            relevant_sources=tuple(str(v) for v in row.get("relevant_sources", [])),
            required_terms=tuple(str(v).lower() for v in row.get("required_terms", [])),
            forbidden_terms=tuple(str(v).lower() for v in row.get("forbidden_terms", [])),
        ))
    if not cases:
        raise ValueError(f"{path}: il dataset non contiene casi")
    return cases


def source_matches(actual: str, expected: str) -> bool:
    """Allow stable suffix/substring expectations for WordPress URLs and uploaded paths."""
    return actual == expected or expected in actual


def retrieval_hit(meta: list[dict], relevant_sources: Iterable[str]) -> bool | None:
    expected = tuple(relevant_sources)
    if not expected:
        return None
    selected = [str(item.get("source_ref", "")) for item in meta if item.get("selected")]
    return all(any(source_matches(actual, wanted) for actual in selected) for wanted in expected)


def classify_answer(
    case: EvalCase,
    context: list[str],
    meta: list[dict],
    *,
    run_llm: bool,
) -> tuple[str, str]:
    """Return (outcome, text). Deterministic scope routing runs even with --no-llm."""
    if not _is_small_talk(case.query) and not _retrieval_is_in_scope(meta):
        return "out_of_scope", ""
    if not run_llm:
        return "answer", ""
    result = chat(_build_system(context), [], case.query)
    if "escalate" in result:
        return "escalate", result["escalate"]
    return "answer", result.get("reply", "")


def score_case(case: EvalCase, *, outcome: str, text: str, hit: bool | None) -> dict:
    normalized = text.lower()
    terms_ok = all(term in normalized for term in case.required_terms)
    forbidden_ok = all(term not in normalized for term in case.forbidden_terms)
    return {
        "id": case.id,
        "query": case.query,
        "expected_outcome": case.expected_outcome,
        "actual_outcome": outcome,
        "outcome_ok": outcome == case.expected_outcome,
        "retrieval_hit": hit,
        "terms_ok": terms_ok,
        "forbidden_ok": forbidden_ok,
        "passed": outcome == case.expected_outcome and hit is not False and terms_ok and forbidden_ok,
        "answer": text,
    }


def summarize(results: list[dict]) -> dict:
    retrieval = [r["retrieval_hit"] for r in results if r["retrieval_hit"] is not None]
    total = len(results)
    return {
        "cases": total,
        "passed": sum(bool(r["passed"]) for r in results),
        "pass_rate": round(sum(bool(r["passed"]) for r in results) / total, 4),
        "outcome_accuracy": round(sum(bool(r["outcome_ok"]) for r in results) / total, 4),
        "retrieval_recall": round(sum(bool(v) for v in retrieval) / len(retrieval), 4) if retrieval else None,
    }


def run(client_id: int, cases: list[EvalCase], *, run_llm: bool) -> tuple[list[dict], dict]:
    results: list[dict] = []
    with Session(engine) as session:
        for case in cases:
            context, meta = retrieve_with_meta(session, client_id, case.query)
            hit = retrieval_hit(meta, case.relevant_sources)
            outcome, text = classify_answer(case, context, meta, run_llm=run_llm)
            results.append(score_case(case, outcome=outcome, text=text, hit=hit))
    return results, summarize(results)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Valuta retrieval e routing RAG su un tenant")
    parser.add_argument("--client-id", required=True, type=int)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--no-llm", action="store_true", help="Valuta retrieval e scope guard senza generare risposte")
    parser.add_argument("--min-pass-rate", type=float, default=0.8)
    parser.add_argument("--output", type=Path, help="Salva il report JSON completo")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 0 <= args.min_pass_rate <= 1:
        print("--min-pass-rate deve essere compreso tra 0 e 1", file=sys.stderr)
        return 2
    try:
        cases = load_cases(args.dataset)
        results, summary = run(args.client_id, cases, run_llm=not args.no_llm)
    except (OSError, ValueError, LLMUnavailableError) as exc:
        print(f"Errore evaluation: {exc}", file=sys.stderr)
        return 2

    report = {"client_id": args.client_id, "dataset": str(args.dataset), "summary": summary, "results": results}
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for result in results:
        marker = "PASS" if result["passed"] else "FAIL"
        print(f"[{marker}] {result['id']}: {result['actual_outcome']} (atteso {result['expected_outcome']})")
    return 0 if summary["pass_rate"] >= args.min_pass_rate else 1


if __name__ == "__main__":
    raise SystemExit(main())
