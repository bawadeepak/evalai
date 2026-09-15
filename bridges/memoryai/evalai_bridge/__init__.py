"""Eval Triage's MemoryAI bridge.

Runs inside MemoryAI's own interpreter (``MEMORYAI_PYTHON``) with this folder on
``PYTHONPATH``; nothing is installed into MemoryAI's environment and its source
is never modified. Speaks newline-delimited JSON on stdin/stdout.
"""

BRIDGE_VERSION = "evalai-bridge-1"
