"""The publication-integrity audit catches each defect it claims to catch, and
nothing on a clean report.

The clean fixture is built with the REAL synthesis and statement functions, so
"clean" means "what the pipeline actually produces", not a hand-written shape
that happens to satisfy the checker.
"""

import copy

import pytest

from app.agents.statements import composition, derive_statements
from app.agents.synthesis import synthesize
from evals.report_integrity import audit

CHUNK_A = "We evaluate GraphRAG on HotpotQA. GraphRAG reaches an F1 of 80.2 on HotpotQA."
CHUNK_B = "On HotpotQA our GraphRAG configuration obtains 91 F1, a strong result."


def _finding(cid, value, quote):
    return {"claim_id": cid, "dimension": "accuracy", "text": f"F1 {value}",
            "metric": "F1", "value": value, "quote": quote,
            "context": {"dataset": "HotpotQA", "task": "multi-hop QA", "model": "GraphRAG"}}


def _clean() -> dict:
    matrix = [
        {"doc_id": "d1", "title": "GraphRAG for multi-hop QA", "year": 2024, "full_text": True,
         "findings": [_finding("c1", "80.2", "GraphRAG reaches an F1 of 80.2 on HotpotQA")],
         "cells": {"accuracy": {"state": "reported", "claim_ids": ["c1"]},
                   "latency": {"state": "not_reported",
                               "coverage": {"queries": 3, "examined": 12, "chunks": 6}}}},
        {"doc_id": "d2", "title": "Scaling graph retrieval", "year": 2025, "full_text": True,
         "findings": [_finding("c2", "91", "our GraphRAG configuration obtains 91 F1")],
         "cells": {"accuracy": {"state": "reported", "claim_ids": ["c2"]},
                   "latency": {"state": "extraction_uncertain", "coverage": {}}}},
    ]
    schema = {"required_dimensions": [{"name": "accuracy", "kind": "quantitative"},
                                      {"name": "latency", "kind": "quantitative"}]}
    syn = synthesize(matrix, {"accuracy": "quantitative", "latency": "quantitative"})
    derived = derive_statements(syn, matrix)

    def claim(cid, text, quote, chunk, doc):
        return {"claim_id": cid, "text": text, "status": "verified", "evidence": [{
            "chunk_id": f"k-{cid}", "quote": quote, "quote_char_start": chunk.find(quote),
            "nli_label": "entailment", "nli_score": 0.97, "chunk_text": chunk,
            "document": {"id": doc, "title": "t", "status": "ready"}}]}

    return {
        "id": "rep1", "title": "GraphRAG accuracy",
        "sections": [
            {"heading": "Accuracy", "status": "verified", "claim_ids": ["c1", "c2"],
             "claims": [claim("c1", "GraphRAG reaches 80.2 F1 on HotpotQA.",
                              "GraphRAG reaches an F1 of 80.2 on HotpotQA", CHUNK_A, "d1"),
                        claim("c2", "A GraphRAG configuration obtains 91 F1 on HotpotQA.",
                              "our GraphRAG configuration obtains 91 F1", CHUNK_B, "d2")]},
            {"heading": "Latency", "status": "gap", "claim_ids": [], "claims": [],
             "gap_note": "No study in the corpus reports latency."},
        ],
        "references": [
            {"document_id": "d1", "title": "GraphRAG for multi-hop QA", "year": 2024,
             "authors": ["A. Author"], "url": "https://arxiv.org/abs/2401.00001"},
            {"document_id": "d2", "title": "Scaling graph retrieval", "year": 2025,
             "authors": ["B. Author"], "url": "https://doi.org/10.1/x"},
        ],
        "confidence": {
            "sections_verified": 1, "sections_total": 2, "low_confidence": False,
            "evidence_matrix": matrix, "evidence_schema": schema, "synthesis": syn,
            "derived_statements": derived,
            "composition": composition(2, len(derived)),
            "scope": {"since_year": 2020, "until_year": 0},
            "funnel": {
                "ladder": {"discovered": 40, "screened": 30, "eligible": 10, "ingested": 4,
                           "full_text_available": 3, "extracted": 2,
                           "included_in_synthesis": 2, "cited_in_report": 2},
                "screened": 30, "screened_in": 10, "screened_out": 20,
                "required_dimensions": ["accuracy", "latency"],
                "cells_total": 4, "cells_reported": 2, "cells_not_reported": 1,
                "cells_not_applicable": 0, "cells_uncertain": 1,
                "claims_verified": 2,
            },
        },
    }


def _codes(payload) -> set[str]:
    return {i["code"] for i in audit(payload)["issues"] if i["severity"] == "error"}


def test_the_clean_fixture_actually_exercises_the_derived_checks():
    p = _clean()
    kinds = {s["kind"] for s in p["confidence"]["derived_statements"]}
    assert "pooled" in kinds, "fixture must produce a pooled D sentence to test D4"


def test_a_clean_report_has_no_errors():
    result = audit(_clean())
    assert result["errors"] == 0, result["issues"]


def _mutate(fn):
    p = copy.deepcopy(_clean())
    fn(p)
    return p


@pytest.mark.parametrize("code,mutation", [
    ("F1", lambda p: p["confidence"]["funnel"]["ladder"].update(extracted=9)),
    ("F2", lambda p: p["confidence"]["funnel"].update(screened_out=5)),
    ("F3", lambda p: p["confidence"]["funnel"].update(cells_total=7)),
    ("F4", lambda p: p["confidence"]["funnel"].update(cells_reported=1, cells_uncertain=2)),
    ("F5", lambda p: p["confidence"]["composition"].update(verified=5)),
    ("F6", lambda p: p["confidence"].update(sections_verified=2)),
    ("C1", lambda p: p["sections"][1].update(status="verified", claim_ids=["c1"],
                                             claims=[p["sections"][0]["claims"][0]])),
    ("C2", lambda p: p["sections"][1].update(status="verified")),
    ("C3", lambda p: p["sections"][1].update(claim_ids=["c9"])),
    ("C6", lambda p: p["sections"][0]["claims"][0]["evidence"][0].update(
        chunk_text="An unrelated passage about something else entirely.")),
    ("C7", lambda p: p["sections"][0]["claims"][0]["evidence"][0].update(nli_label="contradiction")),
    ("M1", lambda p: p["confidence"]["evidence_matrix"][0]["findings"][0].update(claim_id="")),
    ("M2", lambda p: p["confidence"]["evidence_matrix"][0]["cells"]["latency"].update(
        coverage={"queries": 1, "examined": 2, "chunks": 1})),
    ("D1", lambda p: p["confidence"]["derived_statements"][0].update(
        text="A sentence the matrix never produced.")),
    ("D2", lambda p: p["confidence"]["derived_statements"][0].update(doc_ids=["nope"])),
    ("R4", lambda p: p["references"][0].update(year=2012)),
    ("S1", lambda p: (p["sections"][0].update(status="gap", claim_ids=[], claims=[],
                                              gap_note="x"),
                      p["confidence"].update(sections_verified=0),
                      p["confidence"]["funnel"].update(claims_verified=0),
                      p["confidence"]["composition"].update(verified=0))),
])
def test_each_defect_is_caught(code, mutation):
    assert code in _codes(_mutate(mutation))


def test_a_pooled_value_no_study_reported_is_caught():
    def tamper(p):
        for s in p["confidence"]["derived_statements"]:
            if s["kind"] == "pooled":
                s["text"] = s["text"].replace("80.2", "83.5")
    issues = audit(_mutate(tamper))["issues"]
    assert any(i["code"] == "D4" for i in issues)


def test_restraint_is_enforced_on_derived_sentences():
    def tamper(p):
        p["confidence"]["derived_statements"][0]["text"] += " This suggests that the field agrees."
    assert "D3" in _codes(_mutate(tamper))


def test_not_reported_on_an_abstract_only_study_is_an_error():
    def tamper(p):
        p["confidence"]["evidence_matrix"][0]["full_text"] = False
    assert "M2" in _codes(_mutate(tamper))


def test_duplicate_study_and_uncitable_references_are_warnings():
    def tamper(p):
        p["confidence"]["evidence_matrix"][1]["title"] = "GraphRAG for Multi-Hop QA."
        p["references"][1].update(authors=[], url="")
        p["references"].append({"document_id": "d9", "title": "Never cited", "year": 2024})
    issues = audit(_mutate(tamper))["issues"]
    warn = {i["code"] for i in issues if i["severity"] == "warn"}
    assert {"M3", "R1", "R2"} <= warn


# ── run-to-run reproducibility (evals/reproducibility.py) ─────────────────

def test_a_report_compared_with_itself_is_fully_reproducible():
    from evals.reproducibility import compare
    p = _clean()
    r = compare(p, copy.deepcopy(p))
    assert r["corpus"]["jaccard"] == 1.0
    assert r["cells_same_state"]["rate"] == 1.0
    assert r["values_same"]["rate"] == 1.0
    assert r["derived"]["jaccard"] == 1.0


def test_reproducibility_reports_each_kind_of_drift_separately():
    from evals.reproducibility import compare
    a, b = _clean(), _clean()
    b["confidence"]["evidence_matrix"][0]["cells"]["latency"]["state"] = "extraction_uncertain"
    b["confidence"]["evidence_matrix"][1]["findings"][0]["value"] = "90"
    b["confidence"]["evidence_matrix"].append({"title": "A third study", "findings": []})
    r = compare(a, b)
    assert r["corpus"]["shared"] == 2 and r["corpus"]["union"] == 3
    assert r["cells_same_state"] == {"agree": 3, "n": 4, "rate": 0.75}
    assert r["values_same"]["rate"] == 0.5
    assert r["cell_disagreements"][0]["dimension"] == "latency"
