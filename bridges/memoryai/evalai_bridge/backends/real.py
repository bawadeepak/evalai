"""The real MemoryAI backend (runs only in MemoryAI's interpreter).

* Each store gets an explicit ``Settings`` (absolute data directory, unique bank,
  models from the Eval Triage configuration). ``Settings.from_env()``, the UI's
  saved model files and ``Memory.use_models()`` are never used — the last pins
  Ollama models machine-wide.
* ``Runtime._engine_for`` is mirrored (as at memoryai d14259d) only to pass the
  embedding and cross-encoder models loaded by the first store to later ones, so
  every episode does not reload them.
* A proxy around the engine captures ``recall_async`` results so ``Memory.recall``
  runs exactly once and unchanged while its hit ids are still recorded.
* ``memoryai.smalltalk.check`` is wrapped to record every verdict (MemoryAI keeps
  only skip reasons) and, in test/fixture mode only, to inject a classifier
  failure through an httpx mock transport so MemoryAI's own fail-open path runs.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from evalai_bridge.backends.base import Backend, Store
from evalai_bridge.protocol import BridgeError

FALLBACK_PREFIX = "kept because the small-talk check failed"


def _plain(value):
    return value.model_dump() if hasattr(value, "model_dump") else value


class EngineProxy:
    """Delegates everything to the engine; remembers the last recall result."""

    def __init__(self, engine) -> None:
        object.__setattr__(self, "_engine", engine)
        object.__setattr__(self, "last_recall", None)

    def __getattr__(self, name):
        return getattr(self._engine, name)

    def __setattr__(self, name, value):
        if name == "last_recall":
            object.__setattr__(self, name, value)
        else:
            setattr(self._engine, name, value)

    async def recall_async(self, *args, **kwargs):
        result = await self._engine.recall_async(*args, **kwargs)
        object.__setattr__(self, "last_recall", result)
        return result


class RealStore(Store):
    tokenizer = "cl100k_base (MemoryAI's approximate count)"

    def __init__(self, backend: RealBackend, name: str, data_dir: Path, bank: str, settings: dict[str, Any]) -> None:
        super().__init__()
        from memoryai.runtime import Settings

        self.backend, self.name, self.data_dir, self.bank = backend, name, data_dir, bank
        self.settings = Settings(data_dir=data_dir, bank=bank,
                                 llm_model=settings.get("llm_model") or Settings.llm_model,
                                 consolidation_model=settings.get("consolidation_model") or None,
                                 llm_base_url=settings.get("llm_base_url") or Settings.llm_base_url,
                                 small_talk_filter=bool(settings.get("small_talk_filter", True)))
        self.instance = self.settings.instance
        self.rt = self.log = self.memory = None

    async def start(self) -> None:
        from memoryai.events import EventLog
        from memoryai.memory import Memory

        self.rt = SharedRuntime(self.settings, self.backend.shared_models)
        await self.rt.start()
        self.backend.remember_models(self.rt.engine)
        self.rt._engine = EngineProxy(self.rt._engine)
        self.log = EventLog(self.data_dir / "events.db")
        self.memory = Memory(self.rt, self.log)

    async def stop(self) -> None:
        if self.rt is not None:
            if isinstance(self.rt._engine, EngineProxy):
                self.rt._engine = self.rt._engine._engine
            await self.rt.stop()
            self.rt = None
        if self.log is not None:
            self.log.close()
            self.log = None

    async def drop(self) -> dict[str, Any]:
        import pg0

        pg0.drop(self.instance)
        remaining = self.backend.existing_instances()
        if self.instance in remaining:
            raise BridgeError("action_failed", f"pg0 instance {self.instance} still exists after drop")
        return {"dropped": self.instance, "verified_absent": True}

    async def _call(self, coro) -> str:
        try:
            return (await coro)["message"]
        except ValueError as exc:
            raise BridgeError("action_failed", str(exc)) from exc

    async def remember(self, text, actor):
        return await self._call(self.memory.remember(text, actor))

    async def assert_fact(self, text, status):
        return await self._call(self.memory.assert_fact(text, status))

    async def approve(self, event_id):
        return await self._call(self.memory.approve(event_id))

    async def reject(self, event_id):
        return await self._call(self.memory.reject(event_id))

    async def wrong(self, memory_id):
        return await self._call(self.memory.wrong(memory_id))

    async def forget(self, event_id):
        return await self._call(self.memory.forget(event_id))

    async def rebuild(self):
        return await self._call(self.memory.rebuild())

    async def recall(self, query, level, budget):
        proxy = self.rt._engine
        proxy.last_recall = None
        try:
            result = await self.memory.recall(query, level, budget)
        except ValueError as exc:
            raise BridgeError("action_failed", str(exc)) from exc
        captured = _plain(proxy.last_recall) or {}
        hits = [_plain(hit) for hit in captured.get("results") or []]
        return result, [{"id": h.get("id"), "text": h.get("text"), "document_id": h.get("document_id"),
                         "fact_type": h.get("fact_type")} for h in hits]

    def events(self):
        return [{"id": e.id, "at": e.at.isoformat(), "kind": e.kind, "actor": e.actor, "text": e.text,
                 "data": e.data} for e in self.log.all()]

    async def list_units(self, *, state, limit, offset, document_id=None):
        from memoryai.memory import FACT_TYPES

        page = _plain(await self.rt.engine.list_memory_units(
            self.rt.bank, fact_type=FACT_TYPES, state=state, document_id=document_id, limit=limit, offset=offset,
            request_context=self.rt.ctx))
        items = page.get("items", []) if isinstance(page, dict) else page
        return {"items": [_plain(i) for i in items or []],
                "total": page.get("total") if isinstance(page, dict) else None}

    async def memoryai_state(self):
        return await self.memory.state()

    def count_tokens(self, text):
        from memoryai.memory import count_tokens

        return count_tokens(text)


def _shared_runtime_class():
    from hindsight_api import MemoryEngine
    from hindsight_api.engine.task_backend import SyncTaskBackend
    from memoryai.runtime import Runtime

    class _SharedRuntime(Runtime):
        """Runtime whose engines reuse already-loaded embedding and reranking models."""

        def __init__(self, settings, shared: dict[str, Any]) -> None:
            super().__init__(settings)
            self._shared = shared

        def _engine_for(self, models):
            if not self._shared:
                return super()._engine_for(models)
            extraction, consolidation = self._llm(models["extraction"]), self._llm(models["consolidation"])
            return MemoryEngine(
                db_url=self.settings.db_url,
                memory_llm_provider=extraction["provider"], memory_llm_model=extraction["model"],
                memory_llm_base_url=extraction["base_url"], memory_llm_api_key=extraction["api_key"],
                consolidation_llm_provider=consolidation["provider"], consolidation_llm_model=consolidation["model"],
                consolidation_llm_base_url=consolidation["base_url"],
                consolidation_llm_api_key=consolidation["api_key"],
                task_backend=SyncTaskBackend(), run_migrations=True,
                embeddings=self._shared.get("embeddings"), cross_encoder=self._shared.get("cross_encoder"),
            )

    return _SharedRuntime


class _LazyRuntime:
    cls = None


def SharedRuntime(settings, shared):  # noqa: N802 - factory keeps the MemoryAI import lazy
    if _LazyRuntime.cls is None:
        _LazyRuntime.cls = _shared_runtime_class()
    return _LazyRuntime.cls(settings, shared)


class RealBackend(Backend):
    name = "real"

    def __init__(self, stores_root: str, protected_data_dirs: list[str]) -> None:
        super().__init__(stores_root, protected_data_dirs)
        try:
            import memoryai.memory  # noqa: F401 - fails early if MemoryAI or its tokenizer is unavailable
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"MemoryAI is not importable in this interpreter: {type(exc).__name__}: {exc}") from exc
        self.shared_models: dict[str, Any] = {}
        self.share_models = os.environ.get("EVALAI_BRIDGE_SHARE_MODELS", "1") != "0"
        self.current_store: RealStore | None = None
        self._install_smalltalk_wrapper()

    def remember_models(self, engine) -> None:
        if self.share_models and not self.shared_models:
            for attr in ("embeddings", "cross_encoder"):
                value = getattr(engine, attr, None) or getattr(engine, f"_{attr}", None)
                if value is not None:
                    self.shared_models[attr] = value

    def _install_smalltalk_wrapper(self) -> None:
        import httpx
        import memoryai.smalltalk as smalltalk

        original_check, original_ask = smalltalk.check, smalltalk.ask_model
        backend = self

        async def check(text: str, endpoint: dict[str, str]):
            store = backend.current_store
            fault = store.fault if store else None
            if smalltalk.only_filler(text):
                verdict, method = await original_check(text, endpoint), "rule"
            elif fault:
                def handler(request):
                    if fault == "timeout":
                        raise httpx.ReadTimeout("injected by Eval Triage (test mode)", request=request)
                    if fault == "malformed":
                        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
                    return httpx.Response(500, json={"error": "injected by Eval Triage (test mode)"})

                client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
                try:
                    verdict = await original_ask(text, base_url=endpoint["base_url"], model=endpoint["model"],
                                                 api_key=endpoint["api_key"], client=client)
                finally:
                    await client.aclose()
                method = "model"
            else:
                verdict, method = await original_check(text, endpoint), "model"
            if not verdict.keep:
                outcome = "skipped"
            elif verdict.reason.startswith(FALLBACK_PREFIX):
                outcome, method = "fallback", "fallback"
            else:
                outcome = "kept"
            if store is not None:
                store.smalltalk_records.append({"outcome": outcome, "method": method, "reason": verdict.reason,
                                                "seconds": round(verdict.seconds, 3), "fault_injected": fault})
            return verdict

        smalltalk.check = check

    async def execute_action(self, params: dict[str, Any]) -> dict[str, Any]:
        session = self._session(params)
        self.current_store = self._store(session, (params.get("step") or {}).get("store", "main"))
        try:
            return await super().execute_action(params)
        finally:
            self.current_store = None

    def instance_for(self, data_dir: Path) -> str:
        from memoryai.runtime import Settings

        return Settings(data_dir=Path(data_dir)).instance

    def existing_instances(self) -> set[str]:
        import pg0

        names = set()
        for info in pg0.list_instances():
            name = getattr(info, "name", None) or (info.get("name") if isinstance(info, dict) else None)
            if name:
                names.add(name)
        root = Path.home() / ".pg0" / "instances"
        if root.is_dir():
            names |= {p.name for p in root.iterdir()}
        return names

    def make_store(self, name, data_dir, bank, settings) -> Store:
        return RealStore(self, name, data_dir, bank, settings)

    def describe(self) -> dict[str, Any]:
        import memoryai

        source = Path(memoryai.__file__).resolve().parent.parent
        try:
            sha = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True,
                                 timeout=5).stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            sha = None
        try:
            from importlib.metadata import version

            hindsight = version("hindsight-all")
        except Exception:  # noqa: BLE001
            hindsight = None
        return {"memoryai_source": str(source), "memoryai_revision": sha, "hindsight_version": hindsight,
                "shares_models_across_episodes": self.share_models}
