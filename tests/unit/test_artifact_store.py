import hashlib

import pytest

from eval_triage.artifacts.store import ArtifactError, ArtifactStore


def test_put_is_content_addressed_and_idempotent(tmp_path):
    store = ArtifactStore(tmp_path)
    first = store.put_bytes(b"hello")
    second = store.put_bytes(b"hello")
    assert first == second
    assert first.content_hash == hashlib.sha256(b"hello").hexdigest()
    assert store.read_bytes(first.content_hash) == b"hello"
    assert not list((tmp_path / "tmp").iterdir())  # no partial files left behind


def test_hash_validation_blocks_traversal(tmp_path):
    store = ArtifactStore(tmp_path)
    for bad in ["../etc/passwd", "ABC", "0" * 63, "g" * 64]:
        with pytest.raises(ArtifactError):
            store.path_for(bad)


def test_tampered_file_fails_verification(tmp_path):
    store = ArtifactStore(tmp_path)
    blob = store.put_bytes(b"original")
    path = store.path_for(blob.content_hash)
    path.write_bytes(b"tampered")
    with pytest.raises(ArtifactError):
        store.read_bytes(blob.content_hash)


def test_orphans_reported_never_deleted(tmp_path):
    store = ArtifactStore(tmp_path)
    kept = store.put_bytes(b"a").content_hash
    orphan = store.put_bytes(b"b").content_hash
    report = store.orphans({kept, "f" * 64})
    assert report == {"files_without_rows": [orphan], "rows_without_files": ["f" * 64]}
    assert store.exists(orphan)
