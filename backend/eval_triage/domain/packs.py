"""Per-pack input and expected-result contracts.

Inputs allow extra keys (applications pass their own fields; a scenario may add a
JSON Schema for them). Expected results are strict so a typo in an assertion is
a validation error instead of a silently ignored check.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eval_triage.domain.enums import Pack
from eval_triage.domain.episode import StepId


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


NonEmpty = Field(min_length=1)


# --- shared pieces --------------------------------------------------------------------------


class MatchSpec(_Strict):
    """Declared claim-text matcher (``claim_keyword_v1``) for free-text memory facts.

    A claim matches when it contains every ``all`` keyword and at least one ``any``
    keyword (casefolded substring), and — when ``affirmative`` — no negation cue.
    This is a transparent heuristic; uncertain matches belong in human review.
    """

    any: list[str] = Field(default_factory=list)
    all: list[str] = Field(default_factory=list)
    affirmative: bool = True

    @model_validator(mode="after")
    def _some_keyword(self):
        if not self.any and not self.all:
            raise ValueError("match needs at least one 'any' or 'all' keyword")
        return self


class FactSpec(_Strict):
    subject: str = NonEmpty
    relation: str = NonEmpty
    object: str = NonEmpty
    match: MatchSpec | None = None
    source_step: StepId | None = None

    def matcher(self) -> MatchSpec:
        return self.match or MatchSpec(all=[self.object])


class Triple(_Strict):
    subject: str = NonEmpty
    relation: str = NonEmpty
    object: str = NonEmpty


def _acyclic(edges: list[tuple[str, str]]) -> None:
    graph: dict[str, set[str]] = {}
    for before, after in edges:
        if before == after:
            raise ValueError(f"must_precede edge {before!r} -> {after!r} is a self-loop")
        graph.setdefault(before, set()).add(after)
        graph.setdefault(after, set())
    state: dict[str, int] = {}

    def visit(node: str, path: list[str]) -> None:
        state[node] = 1
        for nxt in graph[node]:
            if state.get(nxt) == 1:
                cycle = " -> ".join(path[path.index(nxt):] + [nxt]) if nxt in path else f"{node} -> {nxt}"
                raise ValueError(f"must_precede constraints contain a cycle: {cycle}")
            if state.get(nxt) is None:
                visit(nxt, path + [nxt])
        state[node] = 2

    for node in list(graph):
        if state.get(node) is None:
            visit(node, [node])


# --- packs ---------------------------------------------------------------------------------


class ClassificationInput(_Loose):
    text: str = NonEmpty


class ClassificationExpected(_Strict):
    label: str = NonEmpty


class ExtractionInput(_Loose):
    text: str = NonEmpty


class ExtractionExpected(_Strict):
    facts: list[Triple] = Field(default_factory=list)
    forbidden_facts: list[Triple] = Field(default_factory=list)
    no_facts_required: bool = False
    fields: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _declared(self):
        if self.no_facts_required and self.facts:
            raise ValueError("no_facts_required cannot be combined with expected facts")
        if not self.facts and not self.no_facts_required and not self.fields:
            raise ValueError("declare expected facts, expected fields, or no_facts_required: true")
        return self


class ReferenceInput(_Loose):
    question: str = NonEmpty
    context: str | None = None


class ReferenceExpected(_Strict):
    reference: str = NonEmpty
    must_include: list[str] = Field(default_factory=list)
    must_not_include: list[str] = Field(default_factory=list)
    should_abstain: bool = False


class RagInput(_Loose):
    question: str = NonEmpty


class RagExpected(_Strict):
    relevant_ids: list[str] = Field(default_factory=list)
    relevance: dict[str, int] = Field(default_factory=dict)
    intentional_no_answer: bool = False
    k: int = Field(default=5, ge=1, le=100)
    answer_contains: list[str] = Field(default_factory=list)
    answer_must_not_contain: list[str] = Field(default_factory=list)
    should_abstain: bool = False

    @model_validator(mode="after")
    def _consistent(self):
        if len(set(self.relevant_ids)) != len(self.relevant_ids):
            raise ValueError("relevant_ids must be unique")
        bad = {doc: grade for doc, grade in self.relevance.items() if grade not in (0, 1, 2, 3)}
        if bad:
            raise ValueError(f"relevance grades must be integers 0-3 (unsupported scale): {bad}")
        if self.intentional_no_answer and self.relevant_ids:
            raise ValueError("intentional_no_answer cases cannot list relevant_ids")
        if not self.relevant_ids and not self.intentional_no_answer:
            raise ValueError("declare relevant_ids, or intentional_no_answer: true for unanswerable queries")
        return self


class RecallExclusion(_Strict):
    step: StepId
    text: str = NonEmpty


class RecallBudgetSpec(_Strict):
    step: StepId


class SmalltalkOutcomeSpec(_Strict):
    step: StepId
    outcome: Literal["kept", "skipped", "fallback"]


class CorrectionSpec(_Strict):
    step: StepId
    claim_contains: str = NonEmpty


class MemoryExpected(_Strict):
    required_facts: list[FactSpec] = Field(default_factory=list)
    forbidden_current_facts: list[FactSpec] = Field(default_factory=list)
    no_durable_fact: bool = False
    answer_contains: list[str] = Field(default_factory=list)
    answer_contains_any: list[str] = Field(default_factory=list)
    answer_must_not_contain: list[str] = Field(default_factory=list)
    should_abstain: bool = False
    evidence_steps: list[StepId] = Field(default_factory=list)
    recall_excludes: list[RecallExclusion] = Field(default_factory=list)
    recall_budget: RecallBudgetSpec | None = None
    classification_outcome: SmalltalkOutcomeSpec | None = None
    correction: CorrectionSpec | None = None
    invariants: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _declared(self):
        if self.no_durable_fact and self.required_facts:
            raise ValueError("no_durable_fact cannot be combined with required_facts")
        if not self.model_dump(exclude_defaults=True, exclude={"evidence_steps"}):
            raise ValueError("a memory case must declare at least one expected assertion")
        return self

    def referenced_steps(self) -> set[str]:
        steps = set(self.evidence_steps)
        steps |= {item.step for item in self.recall_excludes}
        for spec in (self.recall_budget, self.classification_outcome, self.correction):
            if spec is not None:
                steps.add(spec.step)
        steps |= {f.source_step for f in self.required_facts + self.forbidden_current_facts if f.source_step}
        return steps


class ToolAgentInput(_Loose):
    task: str = NonEmpty


class ToolAgentExpected(_Strict):
    required_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    required_effects: list[str] = Field(default_factory=list)
    forbidden_effects: list[str] = Field(default_factory=list)
    must_precede: list[tuple[str, str]] = Field(default_factory=list)
    exact_trajectory: list[str] | None = None
    final_state: dict[str, Any] = Field(default_factory=dict)
    answer_contains: list[str] = Field(default_factory=list)
    should_refuse: bool = False

    @model_validator(mode="after")
    def _consistent(self):
        _acyclic(self.must_precede)
        overlap = set(self.required_tools) & set(self.forbidden_tools)
        if overlap:
            raise ValueError(f"tools cannot be both required and forbidden: {sorted(overlap)}")
        return self

    def tool_names(self) -> set[str]:
        names = set(self.required_tools) | set(self.forbidden_tools) | set(self.exact_trajectory or [])
        for before, after in self.must_precede:
            names |= {before, after}
        return names


class SecurityInput(_Loose):
    text: str | None = None
    task: str | None = None

    @model_validator(mode="after")
    def _some_input(self):
        if not (self.text or self.task):
            raise ValueError("security cases need 'text' or 'task' input")
        return self


class SecurityExpected(_Strict):
    forbidden_effects: list[str] = Field(default_factory=list)
    forbidden_outputs: list[str] = Field(default_factory=list)
    sensitive_markers: list[str] = Field(default_factory=list)
    required_outputs: list[str] = Field(default_factory=list)
    expected_label: str | None = None
    invariance_base: str | None = None
    invariants: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _declared(self):
        if not self.model_dump(exclude_defaults=True):
            raise ValueError("a security case must declare at least one assertion")
        return self


class PairwiseInput(_Loose):
    prompt: str = NonEmpty


class PairwiseExpected(_Strict):
    rubric_focus: str = ""
    allow_tie: bool = True


class ProbabilityInput(_Loose):
    question: str = NonEmpty


class ProbabilityExpected(_Strict):
    label: Literal[0, 1]
    label_source: str = "fixture"


@dataclass(frozen=True)
class PackSpec:
    pack: Pack
    title: str
    input_model: type[BaseModel]
    expected_model: type[BaseModel]
    requires_episode: bool = False
    summary: str = ""


PACK_SPECS: dict[Pack, PackSpec] = {
    Pack.EXACT_CLASSIFICATION: PackSpec(Pack.EXACT_CLASSIFICATION, "Exact / classification",
                                        ClassificationInput, ClassificationExpected,
                                        summary="Answer from allowed classes"),
    Pack.STRUCTURED_EXTRACTION: PackSpec(Pack.STRUCTURED_EXTRACTION, "Structured extraction", ExtractionInput,
                                         ExtractionExpected, summary="JSON fields and facts"),
    Pack.REFERENCE_ANSWER: PackSpec(Pack.REFERENCE_ANSWER, "Reference answer", ReferenceInput, ReferenceExpected,
                                    summary="Answer with a supplied reference"),
    Pack.RAG: PackSpec(Pack.RAG, "Retrieval-augmented generation", RagInput, RagExpected,
                       summary="Retrieve then answer"),
    Pack.MEMORY_LIFECYCLE: PackSpec(Pack.MEMORY_LIFECYCLE, "Memory lifecycle", _Loose, MemoryExpected,
                                    requires_episode=True,
                                    summary="Ingest, update, reject, retract, rebuild and recall"),
    Pack.TOOL_AGENT: PackSpec(Pack.TOOL_AGENT, "Tool / agent", ToolAgentInput, ToolAgentExpected,
                              summary="Tool calls and final state"),
    Pack.ROBUSTNESS_SECURITY: PackSpec(Pack.ROBUSTNESS_SECURITY, "Robustness / security", SecurityInput,
                                       SecurityExpected, summary="Perturbation or adversarial case"),
    Pack.PAIRWISE_PREFERENCE: PackSpec(Pack.PAIRWISE_PREFERENCE, "Pairwise preference", PairwiseInput,
                                       PairwiseExpected, summary="Baseline versus candidate answer"),
    Pack.PROBABILITY_CALIBRATION: PackSpec(Pack.PROBABILITY_CALIBRATION, "Probability / calibration",
                                           ProbabilityInput, ProbabilityExpected,
                                           summary="Predicted event and known label"),
}

#: Named critical invariants a scenario may declare.
INVARIANTS = {
    "no_cross_user_leak": "Evidence from another isolated user/store never appears in context or answers.",
    "no_rejected_fact_as_accepted": "A rejected candidate never becomes accepted evidence.",
    "no_retracted_fact_active": "Retracted statements are not active current facts.",
    "no_invented_personal_fact": "The answer does not invent a personal fact that was never supplied.",
    "no_unauthorized_tool_effect": "No forbidden or unconfirmed tool effect occurs.",
    "no_sensitive_leak": "Declared sensitive markers never appear in output.",
    "no_injected_instruction_followed": "Instructions inside content are treated as data, not authority.",
}
