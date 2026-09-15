import pytest
from pydantic import TypeAdapter, ValidationError

from eval_triage.domain.episode import Step, episode_errors, step_dependencies
from eval_triage.domain.refs import RefError, parse_ref, resolve_ref

steps_adapter = TypeAdapter(list[Step])


def steps(*raw):
    return steps_adapter.validate_python(list(raw))


@pytest.mark.parametrize("ref,expected", [
    ("r1.context", ("r1", ("context",))),
    ("r1.facts[0].hit_id", ("r1", ("facts", 0, "hit_id"))),
    ("step-2.a.b[3]", ("step-2", ("a", "b", 3))),
])
def test_parse_valid_refs(ref, expected):
    assert parse_ref(ref) == expected


@pytest.mark.parametrize("ref", [
    "r1", "r1.", "r1..x", "r1.context; rm -rf /", "__import__('os')", "r1.a[b]", "r1.{{x}}",
    "1abc.x", "r1[1000000]", "r1" + ".a" * 17, "", "r1.context " + "x" * 400,
])
def test_invalid_refs_rejected(ref):
    with pytest.raises(RefError):
        parse_ref(ref)


def test_resolve_walks_only_dicts_and_lists():
    outputs = {"r1": {"context": "ctx", "facts": [{"hit_id": "h1"}]}}
    assert resolve_ref("r1.context", outputs) == "ctx"
    assert resolve_ref("r1.facts[0].hit_id", outputs) == "h1"
    for bad in ("r2.context", "r1.missing", "r1.facts[3].hit_id", "r1.context.upper"):
        with pytest.raises(RefError):
            resolve_ref(bad, outputs)


def test_action_union_rejects_unknown_actions_and_bad_args():
    with pytest.raises(ValidationError):
        steps({"id": "x", "action": "shell", "args": {"cmd": "ls"}})
    with pytest.raises(ValidationError):
        steps({"id": "x", "action": "remember", "args": {"text": ""}})
    with pytest.raises(ValidationError):
        steps({"id": "x", "action": "recall", "args": {"query": "q", "budget": 0}})
    with pytest.raises(ValidationError):  # extra fields are typos, not ignored
        steps({"id": "x", "action": "remember", "args": {"text": "t", "extra": 1}})
    with pytest.raises(ValidationError):
        steps({"id": "x", "action": "generate", "args": {"question": "q", "context_ref": "eval(1)"}})


def test_semantic_episode_errors():
    episode = steps(
        {"id": "a", "action": "remember", "args": {"text": "hi"}},
        {"id": "a", "action": "recall", "args": {"query": "q"}},
        {"id": "g", "action": "generate", "args": {"question": "q", "context_ref": "later.context"}},
        {"id": "p", "action": "approve", "args": {"step": "a"}},
        {"id": "f", "action": "forget", "args": {"step": "g"}},
        {"id": "o", "store": "other", "action": "forget", "args": {"step": "a"}},
        {"id": "later", "action": "recall", "args": {"query": "q"}},
    )
    messages = [message for _, message in episode_errors(episode)]
    assert any("duplicate step id" in m for m in messages)
    assert any("must point to an earlier step" in m for m in messages)
    assert any("candidate 'assert'" in m for m in messages)
    assert any("'remember' or 'assert'" in m for m in messages)
    assert any("belongs to store" in m for m in messages)


def test_valid_lifecycle_episode_and_dependencies():
    episode = steps(
        {"id": "c1", "action": "assert", "args": {"text": "fact", "status": "candidate"}},
        {"id": "x1", "action": "reject", "args": {"step": "c1"}},
        {"id": "r1", "action": "recall", "args": {"query": "q"}},
        {"id": "a1", "action": "generate", "args": {"question": "q", "context_ref": "r1.context"}},
        {"id": "b1", "action": "rebuild"},
    )
    assert episode_errors(episode) == []
    assert step_dependencies(episode[1]) == {"c1"}
    assert step_dependencies(episode[3]) == {"r1"}
    assert step_dependencies(episode[4]) == set()
