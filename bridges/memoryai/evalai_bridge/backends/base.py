"""Backend-agnostic bridge logic.

Real and fake backends implement the same small set of *store primitives*
(mirroring ``memoryai.memory.Memory``); everything evidence-related — isolation
checks, the ownership manifest, event-id diffing, correction target
resolution, recall enrichment, the paged state snapshot and store cleanup —
lives here once, so both backends produce identical output shapes.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import shutil
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evalai_bridge import BRIDGE_VERSION
from evalai_bridge.protocol import PROTOCOL_VERSION, BridgeError

OWNERSHIP_FILE = ".evalai-owned.json"
PAGE = 500
MEMORYAI_LIST_LIMIT = 200
WINDOW_TURNS = 6
DOCUMENT = re.compile(r"(turn|assert)-(\d+)")


def split_fact(text: str) -> tuple[str, str]:
    claim, *qualifiers = (text or "").split(" | ")
    return claim.strip(), " · ".join(q.strip() for q in qualifiers)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def dir_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0


class Store:
    """One isolated store. Subclasses implement the primitives."""

    name: str
    data_dir: Path
    bank: str
    instance: str
    tokenizer: str

    def __init__(self) -> None:
        self.smalltalk_records: list[dict[str, Any]] = []
        self.fault: str | None = None

    # primitives -------------------------------------------------------------------------------
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def drop(self) -> dict[str, Any]: ...
    async def remember(self, text: str, actor: str) -> str: ...
    async def assert_fact(self, text: str, status: str) -> str: ...
    async def approve(self, event_id: int) -> str: ...
    async def reject(self, event_id: int) -> str: ...
    async def wrong(self, memory_id: str) -> str: ...
    async def forget(self, event_id: int) -> str: ...
    async def rebuild(self) -> str: ...
    async def recall(self, query: str, level: str, budget: int) -> tuple[dict[str, Any], list[dict[str, Any]]]: ...
    def events(self) -> list[dict[str, Any]]: ...
    async def list_units(self, *, state: str, limit: int, offset: int,
                         document_id: str | None = None) -> dict[str, Any]: ...
    async def memoryai_state(self) -> dict[str, Any]: ...
    def count_tokens(self, text: str) -> int: ...


class Session:
    def __init__(self, session_id: str, stores: dict[str, Store], owner: dict[str, Any]) -> None:
        self.id = session_id
        self.stores = stores
        self.owner = owner


class Backend:
    name = "base"

    def __init__(self, stores_root: str, protected_data_dirs: list[str]) -> None:
        self.stores_root = Path(stores_root).expanduser().resolve()
        self.protected = [Path(p).expanduser().resolve() for p in protected_data_dirs]
        self.sessions: dict[str, Session] = {}
        self.current: Session | None = None

    # subclass hooks ---------------------------------------------------------------------------
    def make_store(self, name: str, data_dir: Path, bank: str, settings: dict[str, Any]) -> Store:
        raise NotImplementedError

    def instance_for(self, data_dir: Path) -> str:
        raise NotImplementedError

    def existing_instances(self) -> set[str]:
        return set()

    def describe(self) -> dict[str, Any]:
        return {}

    async def shutdown(self) -> None:
        for session in list(self.sessions.values()):
            for store in session.stores.values():
                with contextlib.suppress(Exception):
                    await store.stop()
        self.sessions.clear()

    # dispatch ---------------------------------------------------------------------------------
    async def dispatch(self, command: str, params: dict[str, Any]) -> dict[str, Any]:
        handlers = {"hello": self.hello, "prepare": self.prepare, "execute_action": self.execute_action,
                    "inspect_state": self.inspect_state, "close": self.close, "drop_store": self.drop_store,
                    "shutdown": self._shutdown}
        if command not in handlers:
            # Notably there is no ``clear``: MemoryAI's clear() is never reachable through the bridge.
            raise BridgeError("protocol_error", f"unknown command {command!r}", {"commands": sorted(handlers)})
        return await handlers[command](params)

    async def _shutdown(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"shutdown": True}

    async def drop_store(self, params: dict[str, Any]) -> dict[str, Any]:
        """Drop a retained store after verifying it belongs to Eval Triage (used by ``evalai memoryai gc``)."""
        data_dir = Path(params.get("data_dir", "")).expanduser().resolve()
        if self.stores_root not in data_dir.parents:
            raise BridgeError("isolation_refused", "store is outside the stores root")
        for protected in self.protected:
            if self.instance_for(protected) == self.instance_for(data_dir):
                raise BridgeError("isolation_refused", "refusing to drop a protected MemoryAI store")
        try:
            manifest = json.loads((data_dir.parent / OWNERSHIP_FILE).read_text())
        except (OSError, ValueError) as exc:
            raise BridgeError("isolation_refused", "ownership manifest missing; refusing to drop") from exc
        if params.get("nonce") is None or manifest.get("nonce") != params.get("nonce"):
            raise BridgeError("isolation_refused", "ownership nonce mismatch; refusing to drop")
        instance = self.instance_for(data_dir)
        if manifest.get("instance") != instance:
            raise BridgeError("isolation_refused", "instance name does not match the ownership manifest")
        store = self.make_store(manifest.get("store", "main"), data_dir, manifest.get("bank", ""), {})
        result = await store.drop()
        shutil.rmtree(data_dir.parent, ignore_errors=True)
        return {**result, "data_dir": str(data_dir), "removed": not data_dir.parent.exists()}

    async def hello(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"protocol_version": PROTOCOL_VERSION, "bridge_version": BRIDGE_VERSION, "backend": self.name,
                "pid": os.getpid(), "stores_root": str(self.stores_root), **self.describe()}

    # isolation --------------------------------------------------------------------------------
    def _plan_dir(self, episode_id: str, store: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", episode_id) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", store):
            raise BridgeError("isolation_refused", "episode and store names must be simple identifiers")
        data_dir = (self.stores_root / episode_id / store / "data").resolve()
        if self.stores_root not in data_dir.parents:
            raise BridgeError("isolation_refused", "store directory escapes the stores root")
        if data_dir.exists() or data_dir.parent.exists():
            raise BridgeError("isolation_refused", f"store directory {data_dir.parent} already exists; a store "
                                                   "path is never reused")
        return data_dir

    def _check_instance(self, data_dir: Path) -> str:
        instance = self.instance_for(data_dir)
        for protected in self.protected:
            if self.instance_for(protected) == instance:
                raise BridgeError("isolation_refused", "refusing to open the store of a protected MemoryAI data "
                                                       "directory")
        if instance in self.existing_instances():
            raise BridgeError("isolation_refused", f"instance {instance} already exists; refusing to reuse it")
        return instance

    async def prepare(self, params: dict[str, Any]) -> dict[str, Any]:
        episode_id = params.get("episode_id") or uuid.uuid4().hex
        stores = params.get("stores") or ["main"]
        settings = params.get("settings") or {}
        owner = params.get("owner") or {}
        nonce = params.get("nonce") or secrets.token_hex(16)
        planned = {name: self._plan_dir(episode_id, name) for name in stores}
        instances = {name: self._check_instance(path) for name, path in planned.items()}
        if len(set(instances.values())) != len(instances):
            raise BridgeError("isolation_refused", "stores in one episode must map to distinct instances")
        opened: dict[str, Store] = {}
        try:
            for name, data_dir in planned.items():
                bank = f"evalai-{episode_id[:12]}-{name}"
                data_dir.mkdir(parents=True)
                manifest = {"nonce": nonce, "instance": instances[name], "data_dir": str(data_dir), "bank": bank,
                            "store": name, "episode_id": episode_id, "owner": owner, "created_at": _now(),
                            "backend": self.name, "bridge_version": BRIDGE_VERSION}
                (data_dir.parent / OWNERSHIP_FILE).write_text(json.dumps(manifest, indent=1))
                store = self.make_store(name, data_dir, bank, settings)
                store.fault = ((params.get("fault_injection") or {}).get("smalltalk")
                               if params.get("test_mode") else None)
                if params.get("fault_injection") and not params.get("test_mode"):
                    raise BridgeError("not_supported", "fault injection is only allowed in test/fixture mode")
                await store.start()
                opened[name] = store
        except BaseException:
            for store in opened.values():
                await store.stop()
            raise
        session = Session(uuid.uuid4().hex, opened, owner)
        self.sessions[session.id] = session
        return {"session_id": session.id, "episode_id": episode_id, "nonce": nonce,
                "stores": {name: {"data_dir": str(s.data_dir), "instance": s.instance, "bank": s.bank,
                                  "events_db": str(s.data_dir / "events.db"), "tokenizer": s.tokenizer}
                           for name, s in opened.items()}}

    def _session(self, params: dict[str, Any]) -> Session:
        session = self.sessions.get(params.get("session_id"))
        if session is None:
            raise BridgeError("unknown_session", "no such session (it may have been closed)")
        return session

    def _store(self, session: Session, name: str) -> Store:
        store = session.stores.get(name or "main")
        if store is None:
            raise BridgeError("action_failed", f"store {name!r} was not prepared for this episode")
        return store

    # actions ----------------------------------------------------------------------------------
    async def execute_action(self, params: dict[str, Any]) -> dict[str, Any]:
        session = self._session(params)
        step, resolved = params.get("step") or {}, params.get("resolved") or {}
        store = self._store(session, step.get("store", "main"))
        action, args = step.get("action"), step.get("args") or {}
        self.current = session
        started = time.monotonic()
        try:
            before = max((e["id"] for e in store.events()), default=0)
            before_ids = {e["id"] for e in store.events()}
            smalltalk_before = len(store.smalltalk_records)
            output = await self._run(store, action, args, resolved)
            after = store.events()
            new = [e for e in after if e["id"] > before and e["id"] not in before_ids]
            output["new_event_ids"] = [e["id"] for e in new]
            output["new_events"] = new
            if action == "remember":
                records = store.smalltalk_records[smalltalk_before:]
                output["smalltalk"] = records[-1] if records else self._unchecked(new)
            output["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
            return output
        finally:
            self.current = None

    @staticmethod
    def _unchecked(new: list[dict[str, Any]]) -> dict[str, Any]:
        if new and new[0].get("data", {}).get("retracts") is not None:
            return {"outcome": "not_checked", "method": "disabled", "reason": "retraction, not checked"}
        return {"outcome": "not_checked", "method": "disabled", "reason": "small-talk filter off"}

    async def _run(self, store: Store, action: str, args: dict[str, Any], resolved: dict[str, Any]) -> dict[str, Any]:
        target = resolved.get("target_event_id")
        if action == "remember":
            return {"message": await store.remember(args["text"], args.get("actor", "user"))}
        if action == "assert":
            return {"message": await store.assert_fact(args["text"], args.get("status", "candidate"))}
        if action in ("approve", "reject", "forget"):
            if not target:
                raise BridgeError("action_failed", f"{action} needs the event created by step {resolved.get('target_step')}")
            method = getattr(store, action)
            return {"message": await method(int(target)), "target_event_id": int(target)}
        if action == "wrong":
            return await self._wrong(store, args, resolved)
        if action == "rebuild":
            message = await store.rebuild()
            rebuild_event = next((e for e in reversed(store.events()) if e.get("data", {}).get("rebuild")), None)
            return {"message": message, "unresolved": (rebuild_event or {}).get("data", {}).get("unresolved", [])}
        if action == "recall":
            return await self._recall(store, args)
        if action == "inspect_state":
            return await self.snapshot(store)
        raise BridgeError("not_supported", f"action {action!r} is not executed by the memory bridge")

    async def _wrong(self, store: Store, args: dict[str, Any], resolved: dict[str, Any]) -> dict[str, Any]:
        target = resolved.get("target_event_id")
        if not target:
            raise BridgeError("action_failed", "wrong needs the event created by its source step")
        candidates = []
        for prefix in ("turn", "assert"):
            document = f"{prefix}-{int(target)}"
            candidates += [(document, item) for item in await self._all_units(store, "valid", document)]
        needle = (args.get("claim_contains") or "").casefold()
        matches = [(doc, item) for doc, item in candidates if needle in (item.get("text") or "").casefold()]
        if not matches:
            raise BridgeError("action_failed", f"no active fact from event {target} matches {needle!r}",
                              {"candidates": [split_fact(i.get("text", ""))[0] for _, i in candidates]})
        document, fact = matches[0]
        message = await store.wrong(str(fact["id"]))
        return {"message": message, "memory_id": str(fact["id"]), "claim": split_fact(fact.get("text", ""))[0],
                "document_id": document, "resolution": "source event -> document -> fact (claim match)",
                "other_matches": [str(i["id"]) for _, i in matches[1:]]}

    async def _all_units(self, store: Store, state: str, document_id: str | None = None) -> list[dict[str, Any]]:
        items, offset = [], 0
        while True:
            page = await store.list_units(state=state, limit=PAGE, offset=offset, document_id=document_id)
            chunk = page.get("items") or []
            items += chunk
            offset += len(chunk)
            if len(chunk) < PAGE:
                return items

    async def _recall(self, store: Store, args: dict[str, Any]) -> dict[str, Any]:
        result, hits = await store.recall(args["query"], args.get("level", "mid"), int(args.get("budget", 400)))
        facts = []
        for n, hit in enumerate(hits, 1):
            document = hit.get("document_id")
            match = DOCUMENT.fullmatch(document or "")
            facts.append({"label": f"F{n}", "text": (hit.get("text") or "").replace(" | ", " · "),
                          "hit_id": str(hit.get("id")) if hit.get("id") is not None else None,
                          "document_id": document, "source_event_id": int(match[2]) if match else None})
        facts_block = "\n".join(["## What is known about this person"] + [f"[{f['label']}] {f['text']}" for f in facts])
        budget = int(args.get("budget", 400))
        events = store.events()
        turns = [e for e in events if e["kind"] == "message" and "retracts" not in e.get("data", {})]
        window: list[dict[str, Any]] = []
        for event in reversed(turns[-WINDOW_TURNS:]):
            trial = [event] + window
            if store.count_tokens(_context(facts_block, trial)) > budget:
                break
            window = trial
        rebuilt = _context(facts_block, window)
        window_lines = [{"label": f"W{n}", "event_id": e["id"], "actor": e["actor"], "text": e["text"],
                         "retracted": "retracted_by" in e.get("data", {}), "skipped": "skipped" in e.get("data", {})}
                        for n, e in enumerate(window, 1)]
        headings = "## What is known about this person\n\n## Recent conversation"
        return {**result, "facts": facts, "window": window_lines, "tokenizer": store.tokenizer,
                "window_verified": rebuilt == result.get("context"),
                "token_counts": {"total": result.get("used"), "facts_block": store.count_tokens(facts_block),
                                 "window": store.count_tokens("\n".join(
                                     f"[{w['label']}] {w['actor']}: {w['text']}" for w in window_lines)),
                                 "headings": store.count_tokens(headings)},
                "budget_note": ("MemoryAI never trims the facts block, so used may exceed budget"
                                if (result.get("used") or 0) > budget else None)}

    async def snapshot(self, store: Store) -> dict[str, Any]:
        facts, exhaustive, totals = [], True, {}
        for state in ("valid", "invalidated"):
            items, offset, total = [], 0, None
            while True:
                page = await store.list_units(state=state, limit=PAGE, offset=offset)
                chunk = page.get("items") or []
                total = page.get("total", total)
                items += chunk
                offset += len(chunk)
                if len(chunk) < PAGE:
                    break
            totals[state] = total
            if total is None or len(items) != total:
                exhaustive = False
            for item in items:
                document = item.get("document_id") or ""
                match = DOCUMENT.fullmatch(document)
                reason = item.get("invalidation_reason") or ""
                facts.append({"memory_id": str(item.get("id")), "claim": split_fact(item.get("text", ""))[0],
                              "state": "active" if state == "valid" else
                              ("withdrawn" if reason.startswith("retracted") else "invalidated"),
                              "source_event_id": int(match[2]) if match else None, "document_id": document or None,
                              "fact_type": item.get("fact_type")})
        mstate = await store.memoryai_state()
        truncated = (len(mstate.get("beliefs", [])) >= MEMORYAI_LIST_LIMIT
                     or len(mstate.get("corrections", [])) >= MEMORYAI_LIST_LIMIT)
        events = store.events()
        queue = [{"event_id": e["id"], "claim": e["text"]} for e in events
                 if e["kind"] == "assertion" and e.get("data", {}).get("status") == "candidate"]
        notes = ["facts listed by paging list_memory_units with offsets; compared with reported totals"]
        if truncated:
            notes.append("MemoryAI's own state() view is capped at 200 facts; this snapshot pages past the cap")
        return {"backend": self.name if self.name != "real" else "memoryai", "store": store.name,
                "exhaustive": exhaustive, "truncated_in_memoryai_state": truncated, "facts": facts, "queue": queue,
                "events": [{"id": e["id"], "kind": e["kind"], "actor": e["actor"], "text": e["text"],
                            "note": e.get("data", {}).get("skipped"), "data": e.get("data", {})} for e in events],
                "counts": {**(mstate.get("counts") or {}), "facts_listed": len(facts),
                           "reported_totals": totals}, "notes": notes}

    async def inspect_state(self, params: dict[str, Any]) -> dict[str, Any]:
        session = self._session(params)
        return await self.snapshot(self._store(session, params.get("store", "main")))

    async def close(self, params: dict[str, Any]) -> dict[str, Any]:
        session = self._session(params)
        retain = params.get("retain", True)
        report = {}
        for name, store in session.stores.items():
            events = store.events()
            await store.stop()
            entry = {"instance": store.instance, "data_dir": str(store.data_dir), "events": events,
                     "disk_bytes": dir_bytes(store.data_dir.parent), "retained": retain}
            if not retain:
                entry["drop"] = await self._drop(store, params.get("nonce"))
            report[name] = entry
        self.sessions.pop(session.id, None)
        return {"stores": report}

    async def _drop(self, store: Store, nonce: str | None) -> dict[str, Any]:
        manifest_path = store.data_dir.parent / OWNERSHIP_FILE
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, ValueError) as exc:
            raise BridgeError("isolation_refused", "ownership manifest missing; refusing to drop") from exc
        if self.stores_root not in store.data_dir.parents:
            raise BridgeError("isolation_refused", "store is outside the stores root")
        if nonce is None or manifest.get("nonce") != nonce:
            raise BridgeError("isolation_refused", "ownership nonce mismatch; refusing to drop")
        if manifest.get("instance") != self.instance_for(store.data_dir):
            raise BridgeError("isolation_refused", "instance name does not match the ownership manifest")
        result = await store.drop()
        shutil.rmtree(store.data_dir.parent, ignore_errors=True)
        return result


def _context(facts_block: str, window: list[dict[str, Any]]) -> str:
    lines = [facts_block, "", "## Recent conversation"]
    lines += [f"[W{n}] {e['actor']}: {e['text']}" for n, e in enumerate(window, 1)]
    return "\n".join(lines)
