# Eval Triage — documentation

The application is implemented in this repository (see the
[repository README](../README.md) for installation and use). Application
guides:

* [Architecture](./architecture.md)
* [Adapters and integrations](./adapters.md) — including the MemoryAI bridge and its cloud boundary
* [Metrics](./metrics.md)
* [Operations](./operations.md)
* [Validation report](./validation-report.md) — test results, limitations and external prerequisites
* [Screenshots](./screenshots/)

The rest of this folder is the original research and build blueprint the
application was built from.

## Research and build blueprint

Research date: 15 September 2026.

### Start here

**For coding:** read [the handoff checklist](./HANDOFF.md), then [the complete implementation plan](./plan.md). Take this entire folder to Claude Code or Codex. The plan is self-contained and includes the formula catalogue. Separate [UI details](./UI_DETAILS.md), [backend contracts](./BACKEND_CONTRACTS.md), and both [first](./SOURCE_TRANSCRIPT_1.md) and [second](./SOURCE_TRANSCRIPT_2.md) source transcripts are included.

1. [Research and open-source comparison](./RESEARCH.md)
2. [Framework, UI, and MemoryAI integration specification](./SPECIFICATION.md)
3. [Formula catalogue and video extraction](./FORMULAS.md)
4. [Executable reference mathematics](./metrics.py), with [tests](./test_metrics.py)

This package was written as a research deliverable and implementation blueprint; `UI_PREVIEW.html` is an interactive design preview with illustrative data. The application built from it now lives in this repository (see above); production deployment remains out of scope.

The research combines both supplied transcripts, direct inspection of selected frames from Josh Tobin's video, current primary documentation and research papers, and a read-only inspection of `/Users/deepakbawa/Documents/AI/memoryai` (HEAD `d14259d99dcf4afa7aafe9ed920f507d25ce5ff3`; an existing untracked `build/` directory was excluded from analysis). The open-source comparison is a documented architecture assessment, not a performance benchmark of installed tools. No paid model calls were made, and the MemoryAI project and its data were not modified.

Validation: all 12 mathematics tests passed with the available local Python. They cover analytic examples, interval boundaries, calibration bins, invalid input handling, and exhaustive small-pool checks of both repeated-success estimators. The interactive design preview was visually checked at desktop and narrow widths; all three case selections and the local review action were exercised. Preview results are synthetic and are not MemoryAI benchmark measurements.

Run the mathematics checks from this directory:

```sh
python3 -m unittest -v test_metrics.py
python3 metrics.py
```

### Recommendation

Build a small, provider-neutral Eval Triage application that owns scenarios, immutable results, statistical analysis, and human review. Start with MemoryAI extraction and memory-lifecycle scenarios. Integrate Inspect AI as the first general execution engine; add Ragas metrics and Promptfoo security-suite imports as separate integrations when needed. Keep DeepEval as the simpler alternative if Python unit-test style evaluations become the main workflow. Avoid operating several overlapping observability platforms in the initial version.

The critical product distinction is **correctness, repeatability, and probability calibration shown separately**, with case-level evidence behind each number.
