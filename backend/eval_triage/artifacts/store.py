"""Content-addressed artifact files.

Bytes are written to a temporary file, flushed, fsynced, hashed and atomically
renamed to ``<root>/<aa>/<bb>/<sha256>``. Database rows reference artifacts by
hash only after the file is durable. Nothing in this module deletes evidence;
:meth:`ArtifactStore.orphans` only reports.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eval_triage.domain.canonical import canonical_bytes

_HASH = re.compile(r"^[0-9a-f]{64}$")


class ArtifactError(ValueError):
    pass


@dataclass(frozen=True)
class StoredBlob:
    content_hash: str
    relative_path: str
    byte_length: int


def validate_hash(value: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ArtifactError("artifact hash must be 64 lowercase hex characters")
    return value


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._tmp = self.root / "tmp"

    def relative_path(self, content_hash: str) -> str:
        h = validate_hash(content_hash)
        return f"{h[:2]}/{h[2:4]}/{h}"

    def path_for(self, content_hash: str) -> Path:
        return self.root / self.relative_path(content_hash)

    def exists(self, content_hash: str) -> bool:
        return self.path_for(content_hash).is_file()

    def put_bytes(self, data: bytes) -> StoredBlob:
        if not isinstance(data, (bytes, bytearray)):
            raise ArtifactError("artifact content must be bytes")
        digest = hashlib.sha256(data).hexdigest()
        final = self.path_for(digest)
        if final.is_file():
            if final.stat().st_size != len(data):
                raise ArtifactError(f"existing artifact {digest} has unexpected size; refusing to overwrite")
            return StoredBlob(digest, self.relative_path(digest), len(data))
        final.parent.mkdir(parents=True, exist_ok=True)
        self._tmp.mkdir(parents=True, exist_ok=True)
        tmp = self._tmp / f"{digest}.{uuid.uuid4().hex}.part"
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, final)
        return StoredBlob(digest, self.relative_path(digest), len(data))

    def put_json(self, value: Any) -> StoredBlob:
        return self.put_bytes(canonical_bytes(value))

    def put_text(self, text: str) -> StoredBlob:
        return self.put_bytes(text.encode("utf-8"))

    def read_bytes(self, content_hash: str, verify: bool = True) -> bytes:
        path = self.path_for(content_hash)
        if not path.is_file():
            raise FileNotFoundError(content_hash)
        data = path.read_bytes()
        if verify and hashlib.sha256(data).hexdigest() != content_hash:
            raise ArtifactError(f"artifact {content_hash} failed hash verification")
        return data

    def iter_hashes(self):
        if not self.root.is_dir():
            return
        for first in sorted(self.root.iterdir()):
            if first.name == "tmp" or not first.is_dir():
                continue
            for second in sorted(first.iterdir()):
                for item in sorted(second.iterdir()):
                    if _HASH.fullmatch(item.name):
                        yield item.name

    def orphans(self, referenced: set[str]) -> dict[str, list[str]]:
        """Report (never delete) files without rows and rows without files."""
        on_disk = set(self.iter_hashes())
        return {
            "files_without_rows": sorted(on_disk - referenced),
            "rows_without_files": sorted(referenced - on_disk),
        }
