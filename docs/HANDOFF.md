# Eval Triage — files to take to Claude Code or Codex

## Recommended: take this entire folder

Copy `eval-triage/` into the coding agent's workspace. Start with `plan.md`. It contains the implementation requirements and full formula catalogue; the other files preserve the detailed research and supporting evidence.

| File | Purpose | Take it? |
|---|---|---|
| `plan.md` | Complete implementation plan: stack, UI, schemas, APIs, workers, adapters, formulas, tests, milestones | **Required** |
| `RESEARCH.md` | Video analysis, open-source comparisons, primary sources, recommendations | **Yes** |
| `FORMULAS.md` | Separate mathematical catalogue with provenance, assumptions and edge cases | **Yes** |
| `UI_DETAILS.md` | Detailed screens, workflows, layouts, interactions and UI states | **Yes** |
| `BACKEND_CONTRACTS.md` | Data model, execution, MemoryAI bridge, adapters, API and validation requirements | **Yes** |
| `SPECIFICATION.md` | Earlier research specification and MemoryAI source mapping | **Yes** |
| `SOURCE_TRANSCRIPT_1.md` | First user-supplied video transcript | **Yes** |
| `SOURCE_TRANSCRIPT_2.md` | Second user-supplied video transcript | **Yes** |
| `README.md` | Research package context and validation history | **Yes** |
| `HANDOFF.md` | This checklist and coding-agent prompt | **Yes** |
| `UI_PREVIEW.html` | Portable interactive design reference with synthetic data | Recommended |
| `metrics.py` | Small executable reference implementation for a subset of formulas | Recommended |
| `test_metrics.py` | Twelve reference math tests | Recommended |

`plan.md` takes precedence when the earlier `SPECIFICATION.md` lists alternatives. The standalone root-level `plan.md` is an identical convenience copy; you do not need to take two copies.

## Also make the existing backend accessible

The coding agent needs the actual MemoryAI source checkout to implement and verify the bridge:

```text
/Users/deepakbawa/Documents/AI/memoryai
```

The backend source is **not included** in this package. If using another machine, copy/clone that project separately and set `MEMORYAI_SOURCE_PATH` and `MEMORYAI_PYTHON` to the destination paths. Do not copy real memory databases or credentials as test fixtures. The source inspection in these documents refers to commit `d14259d99dcf4afa7aafe9ed920f507d25ce5ff3`; reinspect any changed checkout.

## Prompt to give the coding agent

```text
Read HANDOFF.md and plan.md, then use the companion research, formula,
UI, and backend documents as supporting context. Implement the entire
Eval Triage local application end to end in eval-triage-app/.

Follow all implementation milestones and the definition of done in plan.md.
Do not stop after scaffolding or a mock UI. Build working persistence,
execution, provider adapters, the isolated MemoryAI bridge, graders,
statistics, calibration, review, comparison, import/export and the UI.

Preserve existing MemoryAI source and real user data. Use isolated synthetic
fixtures. Make backend paths and provider configurations configurable.
Use the deterministic demo adapter when credentials are absent, clearly
label demo results, and report live checks as skipped rather than passed.

Run the specified automated checks and document actual results. Deliver
the completed app, exact setup/start commands, and a concise report of any
remaining external prerequisites or unverified live integrations.
```

## Formula provenance

The package includes all formulas specified for the application. The second video's inspected accuracy-gap and slice diagrams are distinguished from the additional statistical methods. It is **not an exhaustive frame-by-frame mathematical transcription of the entire video**. The full supplied transcript is included so further source verification is possible. Do not relabel the added probability/calibration formulas as formulas displayed in that video.

## Current deliverable status

This package is research and an implementation plan. `UI_PREVIEW.html` is a design preview, and the Python files cover only reference mathematics. The complete application and live backend adapters still need to be implemented. The package requires no access to this conversation.
