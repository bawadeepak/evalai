"""Deterministic check vocabulary (implemented in ``eval_triage.graders``)."""

from __future__ import annotations

from eval_triage.domain.enums import Pack

#: check name -> (packs it is meant for, one-line description). ``None`` = any pack.
CHECKS: dict[str, tuple[frozenset[Pack] | None, str]] = {
    "exact_match": (None, "Byte-for-byte UTF-8 equality with the reference/label"),
    "normalized_match": (None, "Casefolded, whitespace-collapsed equality (a separately named metric)"),
    "label_match": (frozenset({Pack.EXACT_CLASSIFICATION, Pack.ROBUSTNESS_SECURITY}),
                    "Predicted label equals the expected label or an allowed alternative"),
    "json_schema": (None, "Output parses as JSON and satisfies the declared output schema"),
    "field_assertions": (frozenset({Pack.STRUCTURED_EXTRACTION}), "Expected fields equal (canonical JSON)"),
    "fact_match": (frozenset({Pack.STRUCTURED_EXTRACTION}),
                   "One-to-one normalised triple matching; precision/recall/F1; forbidden facts absent"),
    "required_facts": (frozenset({Pack.MEMORY_LIFECYCLE}), "Required facts are active in the final state"),
    "forbidden_current_facts": (frozenset({Pack.MEMORY_LIFECYCLE}), "Forbidden facts are not active"),
    "no_durable_fact": (frozenset({Pack.MEMORY_LIFECYCLE}), "No durable fact was retained"),
    "recall_excludes": (frozenset({Pack.MEMORY_LIFECYCLE}), "Recall context excludes declared text"),
    "recall_budget": (frozenset({Pack.MEMORY_LIFECYCLE}), "Recall used tokens stay within the requested budget"),
    "classification_outcome": (frozenset({Pack.MEMORY_LIFECYCLE}),
                               "Small-talk classifier outcome (fallback recorded as fallback)"),
    "correction": (frozenset({Pack.MEMORY_LIFECYCLE}),
                   "A correction survives rebuild or is explicitly reported unresolved"),
    "state_checks": (frozenset({Pack.MEMORY_LIFECYCLE}), "In-episode assert_state results"),
    "answer_contains": (None, "Answer contains required strings"),
    "answer_must_not_contain": (None, "Answer omits forbidden strings"),
    "abstention": (None, "Answer abstains when required (abstention_cue_v1) and not otherwise"),
    "retrieval": (frozenset({Pack.RAG}), "Precision@k, recall@k, reciprocal rank, nDCG (numeric metrics)"),
    "tool_constraints": (frozenset({Pack.TOOL_AGENT, Pack.ROBUSTNESS_SECURITY}),
                         "Required/forbidden tools and effects, argument schemas, partial ordering"),
    "trajectory_exact": (frozenset({Pack.TOOL_AGENT}), "Opt-in exact tool-call sequence equality"),
    "invariants": (None, "Declared critical invariants"),
    "leak_check": (frozenset({Pack.ROBUSTNESS_SECURITY}), "Sensitive markers absent from output"),
    "injection_boundary": (frozenset({Pack.ROBUSTNESS_SECURITY, Pack.MEMORY_LIFECYCLE}),
                           "Injected instructions not followed; no forbidden effects"),
    "invariance": (frozenset({Pack.ROBUSTNESS_SECURITY}), "Output matches the declared base case"),
    "probability_record": (frozenset({Pack.PROBABILITY_CALIBRATION}),
                           "Record the predicted probability for a named event (no verdict)"),
}
