"""Deterministic in-memory stand-in for MemoryAI, with the same shapes and quirks.

Mirrors ``memoryai.memory.Memory`` at commit d14259d closely enough that bridge
tests are meaningful without Ollama or Postgres:

* ``remember``/``assert_fact`` return message strings, not ids (ids are diffed);
* the retraction regex, the event log schema and the small-talk rule are
  MemoryAI's own when MemoryAI is importable, otherwise faithful copies
  (including ``all([])`` classifying non-Latin text as small talk);
* ``state()`` lists at most 200 facts while paging sees them all;
* the facts block in recall is never trimmed, so ``used`` can exceed ``budget``;
* rebuild regenerates fact ids and re-applies corrections by claim.

"Extraction" is trivial and declared: the kept message text becomes one fact.
Recorded golden outputs from a live run keep the output shapes honest.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evalai_bridge.backends.base import Backend, Store, split_fact

try:  # MemoryAI's real building blocks, when running in MemoryAI's interpreter
    from memoryai.events import EventLog as _EventLog
    from memoryai.smalltalk import only_filler as _only_filler
    USING_MEMORYAI = True
except ImportError:  # pragma: no cover - exercised when run under Eval Triage's interpreter
    _EventLog = None
    USING_MEMORYAI = False
    FILLER = frozenset(["ok", "okay", "okey", "k", "kk", "alright", "right", "sure", "fine", "yes", "yeah", "yep", "yup", "no", "nope", "nah", "thanks", "thank", "thx", "ty", "cheers", "much", "so", "very", "really", "lots", "a", "lot", "lol", "lmao", "rofl", "haha", "hahaha", "hehe", "heh", "ha", "cool", "nice", "great", "awesome", "perfect", "lovely", "amazing", "brilliant", "good", "hmm", "hm", "ah", "oh", "ooh", "wow", "uh", "um", "got", "it", "that", "that's", "thats", "this", "makes", "sense", "sounds", "true", "totally", "exactly", "indeed", "hi", "hello", "hey", "morning", "evening", "night", "bye", "goodbye", "see", "you", "ya", "later", "soon", "welcome", "helpful", "useful", "appreciate", "appreciated"])
    _WORDS = re.compile(r"[a-z']+")

    def _only_filler(text: str) -> bool:
        return all(word in FILLER for word in _WORDS.findall(text.lower().replace("’", "'")))

_RETRACTION = re.compile(r"^\s*(please\s+)?(ignore|forget|disregard|scratch)\s+"
                         r"(that|this|it|what i (just )?said|my last message)\b", re.IGNORECASE)
USER_WRONG = "user: that's wrong"
LIST_LIMIT = 200
_QUESTION = re.compile(r"\?\s*$")


class _LocalEventLog:
    """Schema-identical copy of memoryai.events.EventLog (used only without MemoryAI)."""

    def __init__(self, path: Path) -> None:
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,"
                         " kind TEXT NOT NULL, actor TEXT NOT NULL, text TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}')")
        self._db.commit()

    def append(self, kind, actor, text, /, **data):
        at = datetime.now(UTC)
        cur = self._db.execute("INSERT INTO events (at, kind, actor, text, data) VALUES (?, ?, ?, ?, ?)",
                               (at.isoformat(), kind, actor, text, json.dumps(data)))
        self._db.commit()
        return _Ev(cur.lastrowid, at, kind, actor, text, data)

    def get(self, event_id):
        row = self._db.execute("SELECT id, at, kind, actor, text, data FROM events WHERE id = ?", (event_id,)).fetchone()
        return _Ev(row[0], datetime.fromisoformat(row[1]), row[2], row[3], row[4], json.loads(row[5])) if row else None

    def all(self):
        return [_Ev(r[0], datetime.fromisoformat(r[1]), r[2], r[3], r[4], json.loads(r[5]))
                for r in self._db.execute("SELECT id, at, kind, actor, text, data FROM events ORDER BY id")]

    def update_data(self, event_id, **changes):
        event = self.get(event_id)
        data = dict(event.data)
        for key, value in changes.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        self._db.execute("UPDATE events SET data = ? WHERE id = ?", (json.dumps(data), event_id))
        self._db.commit()

    def delete(self, event_id):
        self._db.execute("DELETE FROM events WHERE id = ?", (event_id,))
        self._db.commit()

    def close(self):
        self._db.close()


class _Ev:
    def __init__(self, id, at, kind, actor, text, data):  # noqa: A002
        self.id, self.at, self.kind, self.actor, self.text, self.data = id, at, kind, actor, text, data


class FakeStore(Store):
    tokenizer = "fake_whitespace_v1"

    def __init__(self, name: str, data_dir: Path, bank: str, settings: dict[str, Any], instance: str) -> None:
        super().__init__()
        self.name, self.data_dir, self.bank, self.instance = name, data_dir, bank, instance
        self.small_talk_filter = settings.get("small_talk_filter", True)
        self.facts: dict[str, dict[str, Any]] = {}
        self.log = None

    async def start(self) -> None:
        path = self.data_dir / "events.db"
        self.log = _EventLog(path) if _EventLog is not None else _LocalEventLog(path)

    async def stop(self) -> None:
        if self.log is not None:
            self.log.close()
            self.log = None

    async def drop(self) -> dict[str, Any]:
        return {"dropped": self.instance, "verified_absent": True, "note": "fake store has no Postgres instance"}

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    # small talk -----------------------------------------------------------------------------------
    def _check(self, text: str) -> tuple[bool, dict[str, Any]]:
        if _only_filler(text):
            return False, {"outcome": "skipped", "method": "rule",
                           "reason": "small talk: only an acknowledgement or reaction"}
        if self.fault:
            error = {"timeout": "ReadTimeout", "malformed": "JSONDecodeError", "http_500": "HTTPStatusError"}[self.fault]
            return True, {"outcome": "fallback", "method": "fallback",
                          "reason": f"kept because the small-talk check failed ({error})", "fault_injected": self.fault}
        content = [w for w in re.findall(r"\w+", text.lower()) if w not in {"the", "a", "i", "is", "my"}]
        if _QUESTION.search(text) or len(content) < 2:
            return False, {"outcome": "skipped", "method": "fake", "reason": "small talk: nothing lasting to remember"}
        return True, {"outcome": "kept", "method": "fake", "reason": "says something lasting"}

    def _add_fact(self, text: str, document: str) -> None:
        memory_id = str(uuid.uuid4())
        self.facts[memory_id] = {"id": memory_id, "text": f"{text} | Involving: user", "document_id": document,
                                 "state": "valid", "invalidation_reason": None, "fact_type": "world"}

    # primitives -------------------------------------------------------------------------------------
    async def remember(self, text: str, actor: str) -> str:
        delay = float(os.environ.get("EVALAI_BRIDGE_TEST_DELAY", "0") or 0)  # test-only: simulate a slow mutation
        if delay:
            await asyncio.sleep(delay)
        text = text.strip()
        if actor == "user" and _RETRACTION.match(text):
            target = next((e for e in reversed(self.log.all()) if e.kind == "message" and e.actor == "user"
                           and "retracts" not in e.data and "retracted_by" not in e.data
                           and "skipped" not in e.data), None)
            event = self.log.append("message", "user", text, retracts=target.id if target else 0)
            if target is None:
                return "nothing earlier to retract"
            withdrawn = self._withdraw(target.id, event.id)
            self.log.update_data(target.id, retracted_by=event.id)
            return f"withdrew {len(withdrawn)} fact(s) from turn {target.id}"
        event = self.log.append("message", actor, text)
        if self.small_talk_filter:
            keep, verdict = self._check(text)
            self.smalltalk_records.append(verdict)
            if not keep:
                self.log.update_data(event.id, skipped=verdict["reason"])
                return f"turn {event.id} not stored: {verdict['reason']}"
        self._add_fact(text, f"turn-{event.id}")
        return f"remembered turn {event.id}"

    def _withdraw(self, target_id: int, by_id: int) -> list[dict[str, Any]]:
        withdrawn = []
        for fact in self.facts.values():
            if fact["document_id"] == f"turn-{target_id}" and fact["state"] == "valid":
                fact.update(state="invalidated", invalidation_reason=f"retracted by event {by_id}")
                withdrawn.append({"id": fact["id"], "text": fact["text"]})
        self.log.update_data(by_id, withdrawn=withdrawn)
        return withdrawn

    async def assert_fact(self, text: str, status: str) -> str:
        event = self.log.append("assertion", "user", text.strip(), status=status)
        if status == "approved":
            self._add_fact(event.text, f"assert-{event.id}")
            return "asserted and believed"
        return "asserted — waiting for your review"

    def _candidate(self, event_id: int):
        event = self.log.get(event_id)
        if event is None or event.kind != "assertion" or event.data.get("status") != "candidate":
            raise ValueError(f"event {event_id} is not waiting for review")
        return event

    async def approve(self, event_id: int) -> str:
        event = self._candidate(event_id)
        self.log.update_data(event.id, status="approved")
        self._add_fact(event.text, f"assert-{event.id}")
        self.log.append("governance", "user", f"approved: {event.text}", assertion=event.id)
        return "approved"

    async def reject(self, event_id: int) -> str:
        event = self._candidate(event_id)
        self.log.update_data(event.id, status="rejected")
        self.log.append("governance", "user", f"rejected: {event.text}", assertion=event.id)
        return "rejected"

    async def wrong(self, memory_id: str) -> str:
        fact = self.facts.get(memory_id)
        if fact is None:
            raise ValueError(f"no fact {memory_id}")
        fact.update(state="invalidated", invalidation_reason=USER_WRONG)
        claim, _ = split_fact(fact["text"])
        self.log.append("governance", "user", f"rejected: {claim}", memory_id=memory_id,
                        document_id=fact["document_id"], text=fact["text"])
        return "recorded as a correction"

    async def forget(self, event_id: int) -> str:
        event = self.log.get(event_id)
        if event is None:
            raise ValueError(f"no event {event_id}")
        documents = {f"turn-{event.id}", f"assert-{event.id}"}
        self.facts = {k: f for k, f in self.facts.items() if f["document_id"] not in documents}
        for withdrawn in event.data.get("withdrawn") or []:
            if withdrawn["id"] in self.facts:
                self.facts[withdrawn["id"]].update(state="valid", invalidation_reason=None)
        if event.data.get("retracts"):
            self.log.update_data(event.data["retracts"], retracted_by=None)
        if event.kind == "governance" and event.data.get("memory_id") in self.facts:
            self.facts[event.data["memory_id"]].update(state="valid", invalidation_reason=None)
        self.log.delete(event.id)
        self.log.append("governance", "user", f"forgot event {event.id} ({event.kind})")
        return f"forgot event {event.id}"

    async def rebuild(self) -> str:
        self.facts = {}
        events = self.log.all()
        turns = assertions = 0
        for event in events:
            if event.kind == "message" and "retracts" not in event.data and "skipped" not in event.data:
                self._add_fact(event.text, f"turn-{event.id}")
                turns += 1
            elif event.kind == "assertion" and event.data.get("status") == "approved":
                self._add_fact(event.text, f"assert-{event.id}")
                assertions += 1
        reapplied, unresolved = 0, []
        for event in events:
            if event.kind == "message" and event.data.get("retracts"):
                self._withdraw(event.data["retracts"], event.id)
            elif event.kind == "governance" and event.data.get("memory_id"):
                match = next((f for f in self.facts.values() if f["state"] == "valid"
                              and f["document_id"] == event.data.get("document_id")
                              and split_fact(f["text"])[0].lower() == split_fact(event.data["text"])[0].lower()), None)
                if match is None:
                    unresolved.append({"text": event.data["text"], "event": event.id})
                    continue
                match.update(state="invalidated", invalidation_reason=USER_WRONG)
                self.log.update_data(event.id, memory_id=match["id"])
                reapplied += 1
        summary = (f"rebuilt: replayed {turns} turns and {assertions} assertions, "
                   f"re-applied {reapplied} corrections, {len(unresolved)} unresolved")
        self.log.append("governance", "system", summary, rebuild=True, unresolved=unresolved)
        return summary

    async def recall(self, query: str, level: str, budget: int):
        words = {w for w in re.findall(r"\w+", query.lower()) if len(w) > 2}
        scored = []
        for fact in self.facts.values():
            if fact["state"] != "valid":
                continue
            overlap = len(words & set(re.findall(r"\w+", fact["text"].lower())))
            scored.append((overlap, fact))
        scored.sort(key=lambda x: (-x[0], x[1]["document_id"]))
        hits = [{"id": f["id"], "text": f["text"], "document_id": f["document_id"]} for _, f in scored]
        facts_block = "\n".join(["## What is known about this person"] +
                                [f"[F{n}] {h['text'].replace(' | ', ' · ')}" for n, h in enumerate(hits, 1)])
        turns = [e for e in self.log.all() if e.kind == "message" and "retracts" not in e.data]
        window = []
        for event in reversed(turns[-6:]):
            trial = [event] + window
            if self.count_tokens(_ctx(facts_block, trial)) > budget:
                break
            window = trial
        context = _ctx(facts_block, window)
        return ({"context": context, "used": self.count_tokens(context), "budget": budget,
                 "recorder": [{"text": h["text"], "score": float(s), "kept": True} for (s, _), h in zip(scored, hits, strict=True)],
                 "suppressed": [], "dropped": []}, hits)

    def events(self) -> list[dict[str, Any]]:
        return [{"id": e.id, "at": e.at.isoformat(), "kind": e.kind, "actor": e.actor, "text": e.text,
                 "data": e.data} for e in self.log.all()]

    async def list_units(self, *, state: str, limit: int, offset: int, document_id: str | None = None):
        rows = sorted((f for f in self.facts.values() if f["state"] == state
                       and (document_id is None or f["document_id"] == document_id)), key=lambda f: f["document_id"])
        return {"items": [dict(r) for r in rows[offset:offset + limit]], "total": len(rows), "limit": limit,
                "offset": offset}

    async def memoryai_state(self) -> dict[str, Any]:
        live = [f for f in self.facts.values() if f["state"] == "valid"][:LIST_LIMIT]
        archived = [f for f in self.facts.values() if f["state"] == "invalidated"][:LIST_LIMIT]
        events = self.log.all()
        return {"beliefs": live, "corrections": [f for f in archived if (f["invalidation_reason"] or "").startswith("user:")],
                "counts": {"events": len(events), "turns": sum(e.kind == "message" for e in events),
                           "facts": len(live), "observations": 0, "documents": len({f["document_id"] for f in live}),
                           "corrections": 0, "withdrawn": 0, "pending_consolidation": 0}}


def _ctx(facts_block: str, window) -> str:
    lines = [facts_block, "", "## Recent conversation"]
    lines += [f"[W{n}] {e.actor}: {e.text}" for n, e in enumerate(window, 1)]
    return "\n".join(lines)


class FakeBackend(Backend):
    name = "fake"

    def instance_for(self, data_dir: Path) -> str:
        return "fake-" + hashlib.sha1(str(data_dir.resolve()).encode()).hexdigest()[:10]

    def make_store(self, name, data_dir, bank, settings) -> Store:
        return FakeStore(name, data_dir, bank, settings, self.instance_for(data_dir))

    def describe(self) -> dict[str, Any]:
        return {"memoryai_building_blocks": USING_MEMORYAI,
                "quirks": ["non-Latin text is small talk by rule (all([]))", "state() lists at most 200 facts",
                           "facts block not trimmed (used may exceed budget)", "rebuild regenerates fact ids",
                           "retracted turns stay in the recall window"],
                "extraction": "declared stand-in: the kept message text becomes one fact"}
