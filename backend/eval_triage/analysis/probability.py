"""Probability Lab analysis over recorded predictions of named binary events.

A probability always belongs to an explicitly named event, a method and a
source version, and was recorded before its label. Calibration mappings are
fitted only on a declared calibration split and evaluated on held-out data.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select

from eval_triage.db.models import CalibrationVersion, ProbabilityRecord
from eval_triage.domain.canonical import content_hash
from eval_triage.statistics import calibration as cal
from eval_triage.statistics import core


def list_events(session, project_id: str) -> list[dict[str, Any]]:
    rows = session.execute(select(ProbabilityRecord.event_definition, ProbabilityRecord.score_type,
                                  ProbabilityRecord.method, func.count(), func.count(ProbabilityRecord.label))
                           .where(ProbabilityRecord.project_id == project_id)
                           .group_by(ProbabilityRecord.event_definition, ProbabilityRecord.score_type,
                                     ProbabilityRecord.method)).all()
    return [{"event_definition": e, "score_type": s, "method": m, "predictions": n, "labels": labelled}
            for e, s, m, n, labelled in rows]


def load_records(session, project_id: str, event_definition: str, split: str | None = None):
    query = select(ProbabilityRecord).where(ProbabilityRecord.project_id == project_id,
                                            ProbabilityRecord.event_definition == event_definition)
    if split:
        query = query.where(ProbabilityRecord.split == split)
    return list(session.scalars(query.order_by(ProbabilityRecord.external_id)))


def _usable(records):
    """Records with a prediction and a label recorded after it."""
    usable, excluded = [], {"no_probability": 0, "no_label": 0, "label_before_prediction": 0}
    for r in records:
        if r.probability is None and r.raw_feature is None:
            excluded["no_probability"] += 1
        elif r.label is None:
            excluded["no_label"] += 1
        elif r.labeled_at is not None and r.labeled_at < r.predicted_at:
            excluded["label_before_prediction"] += 1
        else:
            usable.append(r)
    return usable, excluded


def quality(records, *, calibration: dict | None = None, bins: int = 10, threshold: float = 0.5) -> dict[str, Any]:
    usable, excluded = _usable(records)
    predictions = sum(r.probability is not None for r in records)
    labels = sum(r.label is not None for r in records)
    base = {"n_records": len(records), "n_predictions": predictions, "n_labels": labels,
            "label_coverage": labels / len(records) if records else None, "excluded": excluded,
            "clusters": len({r.cluster_id for r in usable}),
            "classes": {"positive": sum(r.label == 1 for r in usable), "negative": sum(r.label == 0 for r in usable)}}
    if not usable:
        return {**base, "raw": None, "calibrated": None,
                "unavailable_reason": "no labelled predictions in this selection"}
    labels_ = [int(r.label) for r in usable]

    def evaluate(probs: list[float]) -> dict[str, Any]:
        bins_result = core.calibration_bins(probs, labels_, bins)
        for row in bins_result["bins"]:
            row["members"] = [usable[i].external_id for i in row["members"]]
        return {
            "brier": core.brier_score(probs, labels_),
            "log_loss_clipped": core.binary_log_loss(probs, labels_),
            "log_loss_epsilon": 1e-15,
            "ece": bins_result["ece"], "bins": bins_result["bins"], "bin_method": bins_result["method"],
            "selective": core.selective_risk(probs, labels_, threshold),
            "risk_coverage": [{k: v for k, v in point.items() if k != "risk_unavailable_reason"}
                              for point in core.risk_coverage_curve(probs, labels_,
                                                                    [i / 20 for i in range(21)])],
        }

    raw_probs = [r.probability if r.probability is not None else r.raw_feature for r in usable]
    raw_valid = all(p is not None and 0 <= p <= 1 for p in raw_probs)
    raw = evaluate(raw_probs) if raw_valid else None
    calibrated = None
    if calibration is not None:
        feature = calibration["features"].get("feature", "raw_feature")
        values = [getattr(r, feature) for r in usable]
        if any(v is None for v in values):
            calibrated = {"unavailable_reason": f"some records lack the calibration feature {feature!r}"}
        else:
            calibrated = evaluate(cal.apply_calibration(calibration["parameters"], values))
    return {**base, "raw": raw, "raw_unavailable_reason": None if raw_valid else "raw scores are not probabilities",
            "calibrated": calibrated, "threshold": threshold,
            "notes": ["ECE depends on binning and sample size; read it with the bin counts.",
                      "A small ECE on a small or selected dataset is not a release guarantee."]}


def fit_calibration(session, project_id: str, *, event_definition: str, method: str, fit_split: str = "calibration",
                    eval_split: str = "test", feature: str = "raw_feature", feature_transform: str = "identity",
                    min_clusters: int = cal.MIN_CLUSTERS, logical_id: str | None = None) -> CalibrationVersion:
    if method not in ("logistic", "isotonic"):
        raise cal.CalibrationError("method must be logistic or isotonic")
    if fit_split == eval_split:
        raise cal.CalibrationError("the evaluation split must differ from the fitting split")
    if feature not in ("raw_feature", "probability"):
        raise cal.CalibrationError("feature must be raw_feature or probability")
    fit_records, _ = _usable(load_records(session, project_id, event_definition, fit_split))
    eval_records, _ = _usable(load_records(session, project_id, event_definition, eval_split))
    if not fit_records:
        raise cal.CalibrationError(f"no labelled predictions in the {fit_split!r} split")
    leaking = {r.cluster_id for r in fit_records} & {r.cluster_id for r in eval_records}
    if leaking:
        raise cal.CalibrationError(f"clusters {sorted(leaking)[:5]} appear in both splits; split by cluster first")
    info = cal.check_fit_data([r.label for r in fit_records], [r.cluster_id for r in fit_records],
                              [r.split for r in fit_records], fit_split=fit_split, min_clusters=min_clusters)
    x = [getattr(r, feature) for r in fit_records]
    if any(v is None for v in x):
        raise cal.CalibrationError(f"some fitting records lack {feature!r}")
    y = [r.label for r in fit_records]
    params = (cal.fit_logistic(x, y, feature_transform=feature_transform) if method == "logistic"
              else cal.fit_isotonic(x, y))
    features = {"feature": feature, "feature_transform": feature_transform}
    split_hashes = {fit_split: content_hash(sorted(r.external_id for r in fit_records)),
                    eval_split: content_hash(sorted(r.external_id for r in eval_records))}
    validation = {"fit": info, "evaluation_split": eval_split, "evaluation_records": len(eval_records)}
    if eval_records:
        mapping = {"features": features, "parameters": params}
        validation["held_out"] = {k: v for k, v in quality(eval_records, calibration=mapping).items()
                                  if k in ("raw", "calibrated", "clusters", "classes")}
    logical_id = logical_id or str(uuid.uuid4())
    version = (session.scalar(select(func.max(CalibrationVersion.version)).where(
        CalibrationVersion.logical_id == logical_id)) or 0) + 1
    digest = content_hash({"event": event_definition, "method": method, "features": features,
                           "split_hashes": split_hashes, "parameters": params})
    row = CalibrationVersion(project_id=project_id, logical_id=logical_id, version=version,
                             event_definition=event_definition, features=features, fit_method=method, source="fit",
                             split_hashes=split_hashes, parameters=params, validation=validation, hash=digest)
    session.add(row)
    session.flush()
    return row


def import_calibration(session, project_id: str, *, event_definition: str, method: str, features: dict,
                       parameters: dict) -> CalibrationVersion:
    """Import a precomputed mapping. Parameters are validated JSON; pickles are never accepted."""
    if parameters.get("method") != method:
        raise cal.CalibrationError("parameters.method must match method")
    cal.validate_parameters(parameters)
    if features.get("feature") not in ("raw_feature", "probability"):
        raise cal.CalibrationError("features.feature must be raw_feature or probability")
    logical_id = str(uuid.uuid4())
    digest = content_hash({"event": event_definition, "method": method, "features": features,
                           "parameters": parameters, "source": "import"})
    row = CalibrationVersion(project_id=project_id, logical_id=logical_id, version=1,
                             event_definition=event_definition, features=features, fit_method=method,
                             source="import", split_hashes={}, parameters=parameters,
                             validation={"note": "imported mapping; not fitted in this project"}, hash=digest)
    session.add(row)
    session.flush()
    return row
