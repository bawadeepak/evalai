"""NDJSON server loop.

stdout is reserved for protocol messages: at start-up a private duplicate of
file descriptor 1 is kept for the protocol and fd 1 is pointed at stderr, so
output from pg0, model loaders or progress bars cannot corrupt the stream.
Everything runs on one asyncio loop (the asyncpg pool, locks and background
maintenance of Hindsight are loop-bound) and commands are handled sequentially.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback

from evalai_bridge.protocol import PROTOCOL_VERSION, BridgeError


def _protect_stdout():
    protocol_fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return os.fdopen(protocol_fd, "w", buffering=1, encoding="utf-8")


async def handle_line(backend, line: bytes) -> dict:
    try:
        message = json.loads(line)
        if not isinstance(message, dict):
            raise ValueError("request must be an object")
    except ValueError as exc:
        return {"id": None, "ok": False, "error": {"type": "protocol_error", "message": f"invalid request: {exc}"}}
    request_id = message.get("id")
    if message.get("protocol_version", PROTOCOL_VERSION) != PROTOCOL_VERSION:
        return {"id": request_id, "ok": False, "error": {
            "type": "protocol_error", "message": f"unsupported protocol version {message.get('protocol_version')}",
            "details": {"supported": PROTOCOL_VERSION}}}
    try:
        result = await backend.dispatch(message.get("command"), message.get("params") or {})
        return {"id": request_id, "ok": True, "result": result}
    except BridgeError as exc:
        return {"id": request_id, "ok": False, "error": {"type": exc.type, "message": str(exc), "details": exc.details}}
    except Exception as exc:  # noqa: BLE001 - every failure is reported on the protocol, never crashes silently
        print(traceback.format_exc(), file=sys.stderr)
        return {"id": request_id, "ok": False, "error": {"type": "internal_error",
                                                         "message": f"{type(exc).__name__}: {exc}"[:2000]}}


async def serve(backend, out) -> None:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=64 * 1024 * 1024)
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            if not line.strip():
                continue
            response = await handle_line(backend, line)
            out.write(json.dumps(response, ensure_ascii=False, default=str) + "\n")
            out.flush()
            if response.get("ok") and (response.get("result") or {}).get("shutdown"):
                break
    finally:
        await backend.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evalai_bridge")
    parser.add_argument("--backend", choices=["fake", "real"], required=True)
    parser.add_argument("--stores-root", required=True, help="the only directory stores may be created under")
    parser.add_argument("--protected-data-dir", action="append", default=[],
                        help="a real MemoryAI data directory whose store must never be touched")
    args = parser.parse_args(argv)
    out = _protect_stdout()
    if os.environ.get("EVALAI_BRIDGE_TEST_NOISE"):
        # Test-only: libraries that print during start-up must not corrupt the protocol stream.
        print("noise written to stdout by a library")
        os.write(1, b"noise written to file descriptor 1\n")
    if args.backend == "fake":
        from evalai_bridge.backends.fake import FakeBackend

        backend = FakeBackend(args.stores_root, args.protected_data_dir)
    else:
        from evalai_bridge.backends.real import RealBackend

        backend = RealBackend(args.stores_root, args.protected_data_dir)
    asyncio.run(serve(backend, out))
    return 0
