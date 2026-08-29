"""The over-specification guard must reject inventions, not vocabulary.

The guard exists to catch a claim that names something its source never
mentions ("the EU AI Act mandates X" attributed to a paper that only discusses
"regulatory constraints"). It was also rejecting a large share of TRUE findings,
because its tokenizer built entity names that no source could ever contain:

    "(PK, CK, RPK)"                          -> "PK CK RPK"
    "Mechanistic Hallucination Mitigation (MHM)" -> "Mechanistic ... Mitigation MHM"
    "On Gemini-2.5-Flash, Vanilla CoT ..."   -> "Gemini-2.5-Flash Vanilla CoT"
    "Logical Contradiction."                 -> "Logical Contradiction."

Measured on a live run, 10 of 17 gate refusals were this artifact — real,
supported findings discarded, which is the most expensive failure mode the
pipeline has: it looks like rigour and is actually lost evidence.

Both directions are pinned here. A change that makes the ALLOW cases pass by
switching the guard off would fail the CATCH cases.
"""

import pytest

from app.verification.gate import _extract_entities, unsupported_entities


# ── it must still catch genuine over-specification ────────────────────────

@pytest.mark.parametrize("claim,chunk,expected", [
    ("The EU AI Act mandates post-market monitoring of deployed systems.",
     "Regulatory constraints require ongoing oversight of deployed systems.",
     "EU AI Act"),
    ("The method was evaluated on the MegaBench Corpus.",
     "The method was evaluated on a standard benchmark suite.",
     "MegaBench Corpus"),
])
def test_invented_names_are_still_rejected(claim, chunk, expected):
    assert expected in unsupported_entities(claim, chunk)


# ── it must not invent entities out of punctuation ────────────────────────

def test_a_parenthesised_acronym_list_is_not_one_name():
    """"(PK, CK, RPK)" is three references, not the phrase "PK CK RPK"."""
    ents = _extract_entities("It uses three policies (PK, CK, RPK) during sampling.")
    assert "PK CK RPK" not in ents
    assert not unsupported_entities(
        "It uses three policies (PK, CK, RPK) during sampling.",
        "We sample along RPK, PK and CK paths jointly.",
    )


def test_a_name_and_its_parenthesised_acronym_do_not_merge():
    ents = _extract_entities("Mechanistic Hallucination Mitigation (MHM) preserves accuracy.")
    assert "Mechanistic Hallucination Mitigation MHM" not in ents
    assert "Mechanistic Hallucination Mitigation" in ents


def test_a_comma_separates_two_systems():
    ents = _extract_entities("On Gemini-2.5-Flash, Vanilla CoT accuracy dropped.")
    assert "Gemini-2.5-Flash Vanilla CoT" not in ents
    assert not unsupported_entities(
        "On Gemini-2.5-Flash, Vanilla CoT accuracy dropped.",
        "On Gemini-2.5-Flash, Vanilla CoT accuracy dropped from 63.7% to 61.1%.",
    )


@pytest.mark.parametrize("claim,chunk", [
    ("Results improved on Logical Contradiction.",
     "Margins were clearest on Logical Contradiction and Entity Swap."),
    ("A 'Compliance Regime' emerges when context dominates.",
     "The Compliance Regime arises when the posterior dominates the prior."),
])
def test_trailing_punctuation_is_not_part_of_the_name(claim, chunk):
    assert not unsupported_entities(claim, chunk)


# ── the acronym fallback ──────────────────────────────────────────────────

def test_source_using_only_the_acronym_supports_the_full_name():
    """Papers introduce a name once and then abbreviate. A claim written with
    the full name is still supported by a passage that only uses the short
    form — otherwise every results section fails."""
    assert not unsupported_entities(
        "Context-Driven Decomposition (CDD) isolates conflicting premises.",
        "We introduce CDD, which isolates conflicting premises.",
    )


def test_hyphenated_compounds_contribute_each_initial():
    """"Context-Driven Decomposition" abbreviates to CDD, not CD. Deriving CD
    made the fallback miss exactly the systems papers abbreviate most."""
    assert not unsupported_entities(
        "Context-Driven Decomposition improves robustness.",
        "CDD improves controlled-conflict robustness over the baseline.",
    )


def test_the_acronym_fallback_is_deliberately_permissive():
    """Known limitation, documented rather than hidden: an unrelated acronym
    whose initials happen to match will satisfy the fallback. This is the
    accepted cost of not rejecting every claim in a results section, and it is
    safe because entailment (layer 3) still has to pass — the guard is a filter
    on over-specification, never the only check."""
    assert unsupported_entities(
        "The Federated Learning Consortium published the benchmark.",
        "The FLC protocol is unrelated; this paper studies retrieval.",
    ) == []


# ── possessives still terminate a run ─────────────────────────────────────

def test_possessive_terminates_a_run():
    ents = _extract_entities("IBM's AI Fairness 360 toolkit was used.")
    assert "IBM AI Fairness" not in ents
