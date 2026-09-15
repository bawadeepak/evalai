"""Closed vocabularies shared by storage, API and UI."""

from __future__ import annotations

from enum import StrEnum


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    CANCELLED = "cancelled"
    FAILED = "failed"


RUN_TERMINAL = frozenset(
    {RunStatus.COMPLETED, RunStatus.COMPLETED_WITH_ERRORS, RunStatus.CANCELLED, RunStatus.FAILED}
)


class TrialStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PROVIDER_ERROR = "provider_error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    INVALID_OUTPUT = "invalid_output"
    UNSUPPORTED = "unsupported"
    SKIPPED = "skipped"
    # A state-mutating action timed out with unknown completion: the episode is
    # not replayed; it ends here and may be restarted in a fresh store.
    INDETERMINATE = "indeterminate"


TRIAL_TERMINAL = frozenset(set(TrialStatus) - {TrialStatus.PENDING, TrialStatus.RUNNING})
#: Trials whose output exists and can be graded.
TRIAL_HAS_OUTPUT = frozenset({TrialStatus.SUCCESS, TrialStatus.INVALID_OUTPUT})


class AttemptStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PROVIDER_ERROR = "provider_error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    INVALID_OUTPUT = "invalid_output"
    UNSUPPORTED = "unsupported"
    INTERRUPTED = "interrupted"
    INDETERMINATE = "indeterminate"


ATTEMPT_TERMINAL = frozenset(set(AttemptStatus) - {AttemptStatus.RUNNING})


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ABSTAIN = "abstain"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


BINARY_VERDICTS = frozenset({Verdict.PASS, Verdict.FAIL})


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


JOB_TERMINAL = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED})


class JobKind(StrEnum):
    TRIAL = "trial"
    GRADE = "grade"
    CONNECTION_TEST = "connection_test"
    CALIBRATION_FIT = "calibration_fit"
    EXPORT = "export"
    IMPORT = "import"
    PROMPTFOO = "promptfoo"
    INSPECT_RUN = "inspect_run"


class Pack(StrEnum):
    EXACT_CLASSIFICATION = "exact_classification"
    STRUCTURED_EXTRACTION = "structured_extraction"
    REFERENCE_ANSWER = "reference_answer"
    RAG = "rag"
    MEMORY_LIFECYCLE = "memory_lifecycle"
    TOOL_AGENT = "tool_agent"
    ROBUSTNESS_SECURITY = "robustness_security"
    PAIRWISE_PREFERENCE = "pairwise_preference"
    PROBABILITY_CALIBRATION = "probability_calibration"


class ScoreType(StrEnum):
    OBSERVED_RATE = "observed_rate"
    AGREEMENT = "agreement"
    ENTROPY = "entropy"
    RUBRIC_SCORE = "rubric_score"
    TOKEN_LOG_PROBABILITY = "token_log_probability"
    PREDICTED_EVENT_PROBABILITY = "predicted_event_probability"
    POSTERIOR_SUCCESS_PROBABILITY = "posterior_success_probability"
    DISTANCE = "distance"
    COUNT = "count"
    DURATION = "duration"
    CURRENCY = "currency"


#: Score types that are probabilities of *some* event. They still may not be
#: mixed with each other: each carries its own event definition and method.
PROBABILITY_SCORE_TYPES = frozenset(
    {ScoreType.PREDICTED_EVENT_PROBABILITY, ScoreType.POSTERIOR_SUCCESS_PROBABILITY}
)


class Direction(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    NEUTRAL = "neutral"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


SEVERITY_RANK = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}


class Split(StrEnum):
    DEVELOPMENT = "development"
    CALIBRATION = "calibration"
    VALIDATION = "validation"
    TEST = "test"
    REGRESSION = "regression"
    PRODUCTION_AUDIT = "production_audit"


class RepeatMode(StrEnum):
    FULL_EPISODE = "full_episode"
    FROZEN_CONTEXT = "frozen_context"


class CapabilityState(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class ReviewDecision(StrEnum):
    CONFIRM_FAILURE = "confirm_failure"
    ACCEPTABLE_VARIATION = "acceptable_variation"
    AMBIGUOUS = "ambiguous"
    GRADER_INCORRECT = "grader_incorrect"
    REQUEST_MORE_TRIALS = "request_more_trials"
    PROMOTE_TO_REGRESSION = "promote_to_regression"


REVIEW_REASON_REQUIRED = frozenset({ReviewDecision.AMBIGUOUS, ReviewDecision.GRADER_INCORRECT})


class GateVerdict(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    INCONCLUSIVE = "inconclusive"


class GraderKind(StrEnum):
    DETERMINISTIC = "deterministic"
    STRUCTURED = "structured"
    MODEL = "model"
    PAIRWISE = "pairwise"
    EXTERNAL = "external"
