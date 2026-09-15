"""The one shape every displayed number takes.

A ``MetricValue`` always states its definition, units, direction, numerator,
denominator, eligibility, missing count and uncertainty method, and lists the
trials/cases that contributed. An unavailable value is ``None`` *with a reason*
— never zero, never perfect.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eval_triage.domain.enums import Direction, ScoreType


class Uncertainty(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: str
    level: float | None = None
    lower: float | None = None
    upper: float | None = None
    label: str = ""
    note: str = ""


class MetricValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    definition_version: str
    score_type: ScoreType
    value: float | None
    unit: str
    direction: Direction
    numerator: float | None = None
    denominator: float | None = None
    eligible_count: int | None = None
    missing_count: int | None = None
    unavailable_reason: str | None = None
    uncertainty: Uncertainty | None = None
    contributing_trial_ids: list[str] = Field(default_factory=list)
    contributing_case_ids: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _consistent(self):
        if self.value is None:
            if not self.unavailable_reason:
                raise ValueError(f"{self.name}: an unavailable value needs unavailable_reason")
        elif not math.isfinite(self.value):
            raise ValueError(f"{self.name}: value must be finite (record infinities as unavailable with reason)")
        return self

    @classmethod
    def unavailable(cls, name: str, reason: str, *, definition_version: str, score_type: ScoreType, unit: str,
                    direction: Direction, **extra: Any) -> MetricValue:
        return cls(name=name, definition_version=definition_version, score_type=score_type, value=None,
                   unit=unit, direction=direction, unavailable_reason=reason, **extra)
