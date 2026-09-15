"""Paired comparison on the 24-cluster routing suite, incompatibility handling and summaries."""

from tests.integration.helpers import demo_target, import_fixture, make_project, run_all, start_run


def _routing(ctx):
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "demo/routing.scenario.yaml")
    targets = {"baseline": demo_target(ctx, project, "b", profile="baseline"),
               "candidate": demo_target(ctx, project, "c", profile="candidate")}
    run_id = start_run(ctx, project, suite, targets, repeats=5)
    run_all(ctx, seconds=120)
    return project, suite, run_id


def test_routing_comparison_is_compatible_and_honest(client, ctx):
    project, suite, run_id = _routing(ctx)
    body = {"project_id": project, "baseline_run_id": run_id, "baseline_key": "baseline",
            "candidate_run_id": run_id, "candidate_key": "candidate"}
    preview = client.post("/api/v1/comparisons/validate", json=body).json()["data"]
    assert preview["preview"] and preview["compatibility"]["compatible"]
    assert preview["compatibility"]["paired_coverage"] == 1.0
    created = client.post("/api/v1/comparisons", json=body).json()["data"]
    metric = next(m for m in created["metrics"] if m["name"] == "case_pass_rate")
    assert metric["independent_clusters"] == 24 and metric["resamples"] == 10000 and metric["seed"] == 42
    # improvements (R07 +1, R11 +0.2) cancel regressions (R15 -0.2, R19 -1): delta 0 over 24 cases
    assert abs(metric["delta"]) < 1e-9
    assert metric["lower"] < -0.05 < metric["upper"]
    assert created["decision"]["verdict"] == "inconclusive"
    changes = created["case_changes"]
    assert {c["external_id"] for c in changes["improved"]} == {"R07", "R11"}
    assert {c["external_id"] for c in changes["regressed"]} == {"R15", "R19"}
    assert "not the probability" in metric["note"]
    listed = client.get("/api/v1/comparisons", params={"project_id": project}).json()["data"]
    assert listed[0]["id"] == created["id"]
    evidence = client.get(f"/api/v1/comparisons/{created['id']}/export").json()["data"]
    assert run_id in evidence["manifests"]


def test_incompatible_runs_are_descriptive_only(client, ctx):
    project, suite, run_id = _routing(ctx)
    other = import_fixture(ctx, project, "packs/exact_classification/scenario.yaml")
    target = demo_target(ctx, project, "x", profile="baseline")
    other_run = start_run(ctx, project, other, {"baseline": target}, repeats=2)
    run_all(ctx)
    result = client.post("/api/v1/comparisons/validate", json={
        "project_id": project, "baseline_run_id": run_id, "baseline_key": "baseline",
        "candidate_run_id": other_run, "candidate_key": "baseline"}).json()["data"]
    assert result["compatibility"]["compatible"] is False
    failed = {f["check"] for f in result["compatibility"]["findings"] if f["blocks_inference"]}
    # Both scenarios use an identical `label` grader, so grader versions correctly match;
    # the scenario contract and the repeat design differ.
    assert {"scenario", "repeat_design"} <= failed and "grader_versions" not in failed
    assert result["metrics"][0]["delta"] is None and result["decision"]["verdict"] != "ready"


def test_run_summary_numbers_carry_provenance(client, ctx):
    project, suite, run_id = _routing(ctx)
    summary = client.get(f"/api/v1/runs/{run_id}/summary").json()["data"]
    slot = summary["slot_rates"]["candidate"]
    assert slot["scheduled"] == 120 and slot["unresolved"] == 1
    assert slot["target_completion"]["numerator"] == 119 and slot["target_completion"]["denominator"] == 120
    assert len(slot["target_completion"]["contributing_trial_ids"]) == 120
    r11 = next(c for c in summary["cases"] if c["external_id"] == "R11")["candidates"]["candidate"]
    rate = r11["metrics"]["pass_rate"]
    assert (rate["numerator"], rate["denominator"]) == (4, 5) and rate["uncertainty"]["method"] == "wilson"
    assert "Bayesian" in r11["metrics"]["posterior"]["uncertainty"]["label"]
    assert r11["flags"]["flaky"]
    semantic = client.get(f"/api/v1/runs/{run_id}/summary", params={"representation": "semantic"}).json()["data"]
    r07 = next(c for c in semantic["cases"] if c["external_id"] == "R07")["candidates"]["baseline"]
    assert r07["metrics"]["modal_agreement"]["value"] == 1.0 and r07["flags"]["stable_wrong"]
    assert r07["metrics"]["modal_agreement"]["provenance"]["procedure"] == "semantic:pass_rule_outcome_v1"
    query = client.post("/api/v1/statistics/query", json={"run_id": run_id, "metric": "observed_pass_rate",
                                                           "group_by": "slice", "slice_key": "queue"}).json()["data"]
    assert query["definition"]["name"] == "observed_pass_rate" and query["values"]
    mixed = client.post("/api/v1/statistics/query", json={"run_id": run_id, "metric": "observed_pass_rate",
                                                           "combine_with": ["output_entropy"]})
    assert mixed.status_code == 422 and "incompatible score types" in mixed.json()["error"]["message"]


def test_cancelled_run_cannot_be_ready(client, ctx):
    project, suite, run_id = _routing(ctx)
    targets = {"candidate": demo_target(ctx, project, "c2", profile="baseline")}
    cancelled = start_run(ctx, project, suite, targets, repeats=5)
    client.post(f"/api/v1/runs/{cancelled}/cancel")
    run_all(ctx)
    result = client.post("/api/v1/comparisons/validate", json={
        "project_id": project, "baseline_run_id": run_id, "baseline_key": "baseline",
        "candidate_run_id": cancelled, "candidate_key": "candidate"}).json()["data"]
    assert result["decision"]["verdict"] != "ready"
    assert any("cancelled" in r for r in result["decision"]["reasons"])
