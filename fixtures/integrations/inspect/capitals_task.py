"""A tiny Inspect task used by the real-package integration test.

It runs offline against Inspect's built-in ``mockllm/model``: no provider calls,
no network, deterministic canned output. The scorer's verdicts are therefore
meaningless as quality signals — the test only proves that Eval Triage can run
an Inspect task and import the log it produces.
"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import match
from inspect_ai.solver import generate


@task
def capitals() -> Task:
    return Task(
        dataset=[
            Sample(id="cap-fr", input="What is the capital of France?", target="Paris"),
            Sample(id="cap-au", input="What is the capital of Australia?", target="Canberra"),
        ],
        solver=generate(),
        scorer=match(),
    )
