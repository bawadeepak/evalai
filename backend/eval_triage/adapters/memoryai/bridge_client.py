"""Launch and talk to the MemoryAI bridge subprocess.

* The bridge runs with MemoryAI's interpreter (real backend) and
  ``PYTHONPATH=bridges/memoryai``; nothing is installed into MemoryAI's venv.
* ``MEMORYAI_*`` and ``HINDSIGHT_API_*`` variables are removed from its
  environment; Hugging Face runs offline by default so nothing is downloaded.
* One process serves one candidate configuration; commands are sequential.
  A timeout, protocol error or crash kills the process (its state is unknown)
  and the process is recycled after a fixed number of episodes.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from eval_triage.config import REPO_ROOT, Settings
from eval_triage.security.redaction import redact

BRIDGE_DIR = REPO_ROOT / "bridges" / "memoryai"
RECYCLE_AFTER_EPISODES = 25
START_TIMEOUT = 300.0


class BridgeError(Exception):
    def __init__(self, type_: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.type = type_
        self.details = details or {}


class BridgeCrashed(BridgeError):
    pass


def bridge_env(settings: Settings, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("MEMORYAI_", "HINDSIGHT_API_")) and k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(BRIDGE_DIR)
    env["TOKENIZERS_PARALLELISM"] = "false"
    env["PYTHONUNBUFFERED"] = "1"
    if settings.memoryai_hf_offline:
        env.setdefault("HF_HUB_OFFLINE", "1")
        env.setdefault("TRANSFORMERS_OFFLINE", "1")
    if settings.tiktoken_cache_dir:
        env["TIKTOKEN_CACHE_DIR"] = str(settings.tiktoken_cache_dir)
    env.update(extra or {})
    return env


def bridge_python(settings: Settings, backend: str) -> str:
    if backend == "real":
        return str(settings.resolved_memoryai_python)
    return sys.executable


class BridgeProcess:
    def __init__(self, settings: Settings, backend: str, env_extra: dict[str, str] | None = None) -> None:
        self.settings = settings
        self.backend = backend
        self.env_extra = env_extra or {}
        self.proc: asyncio.subprocess.Process | None = None
        self.hello: dict[str, Any] = {}
        self.stderr_tail: deque[str] = deque(maxlen=200)
        self.episodes = 0
        self.lock = asyncio.Lock()
        self._stderr_task: asyncio.Task | None = None

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def start(self) -> dict[str, Any]:
        stores_root = self.settings.memoryai_stores_dir
        stores_root.mkdir(parents=True, exist_ok=True)
        args = [bridge_python(self.settings, self.backend), "-m", "evalai_bridge", "--backend", self.backend,
                "--stores-root", str(stores_root),
                "--protected-data-dir", str(self.settings.memoryai_source_path / "data")]
        self.proc = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=bridge_env(self.settings, self.env_extra), cwd=str(BRIDGE_DIR), limit=64 * 1024 * 1024)
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        self.hello = await self.request("hello", timeout=START_TIMEOUT)
        return self.hello

    async def _drain_stderr(self) -> None:
        assert self.proc is not None and self.proc.stderr is not None
        while True:
            line = await self.proc.stderr.readline()
            if not line:
                return
            self.stderr_tail.append(redact(line.decode("utf-8", "replace").rstrip())[0])

    def diagnostics(self) -> str:
        return "\n".join(list(self.stderr_tail)[-20:])

    async def request(self, command: str, params: dict[str, Any] | None = None, timeout: float = 120.0) -> dict:
        if not self.alive:
            raise BridgeCrashed("bridge_crashed", "the bridge process is not running",
                                {"stderr": self.diagnostics(), "returncode": getattr(self.proc, "returncode", None)})
        request_id = uuid.uuid4().hex
        line = json.dumps({"id": request_id, "protocol_version": 1, "command": command, "params": params or {}},
                          ensure_ascii=False) + "\n"
        try:
            self.proc.stdin.write(line.encode("utf-8"))
            await self.proc.stdin.drain()
            raw = await asyncio.wait_for(self.proc.stdout.readline(), timeout=timeout)
        except (TimeoutError, asyncio.CancelledError):
            # The command may still be running and would answer later, desynchronising
            # the protocol; its outcome is unknown, so the process is discarded.
            await asyncio.shield(self.kill())
            raise
        except (BrokenPipeError, ConnectionResetError) as exc:
            await self.kill()
            raise BridgeCrashed("bridge_crashed", f"bridge pipe closed: {exc}", {"stderr": self.diagnostics()}) from exc
        if not raw:
            await self.kill()
            raise BridgeCrashed("bridge_crashed", "the bridge process exited",
                                {"stderr": self.diagnostics(), "returncode": self.proc.returncode})
        try:
            response = json.loads(raw)
        except ValueError as exc:
            await self.kill()
            raise BridgeError("protocol_error", "the bridge wrote a non-protocol line to stdout") from exc
        if response.get("id") != request_id:
            await self.kill()
            raise BridgeError("protocol_error", "response id does not match the request")
        if not response.get("ok"):
            error = response.get("error") or {}
            raise BridgeError(error.get("type", "internal_error"), error.get("message", "bridge error"),
                              error.get("details"))
        return response.get("result") or {}

    async def kill(self) -> None:
        if self.proc is not None and self.proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self.proc.kill()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.proc.wait(), timeout=10)
        if self._stderr_task is not None:
            self._stderr_task.cancel()

    async def stop(self) -> None:
        if self.alive:
            with contextlib.suppress(Exception):
                await self.request("shutdown", timeout=30)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.proc.wait(), timeout=30)
        await self.kill()


class BridgePool:
    """One bridge process per (candidate configuration, backend), recycled regularly."""

    def __init__(self) -> None:
        self.processes: dict[tuple, BridgeProcess] = {}
        self.recycle_after = RECYCLE_AFTER_EPISODES

    async def acquire(self, settings: Settings, key: tuple, backend: str,
                      env_extra: dict[str, str] | None = None) -> BridgeProcess:
        process = self.processes.get(key)
        if process is None or not process.alive:
            process = BridgeProcess(settings, backend, env_extra)
            await process.start()
            self.processes[key] = process
        return process

    async def release(self, key: tuple, process: BridgeProcess, healthy: bool) -> None:
        process.episodes += 1
        if not healthy or not process.alive or process.episodes >= self.recycle_after:
            self.processes.pop(key, None)
            await process.stop()

    async def close_all(self) -> None:
        for process in list(self.processes.values()):
            await process.stop()
        self.processes.clear()


_POOLS: dict[int, BridgePool] = {}


def pool() -> BridgePool:
    loop_id = id(asyncio.get_running_loop())
    return _POOLS.setdefault(loop_id, BridgePool())


async def close_all() -> None:
    current = _POOLS.pop(id(asyncio.get_running_loop()), None)
    if current is not None:
        await current.close_all()


def stores_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0
