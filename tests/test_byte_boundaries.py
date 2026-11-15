"""Counterexamples at the source-byte and operational-metadata trust boundaries."""

import json
from contextlib import contextmanager
from pathlib import Path

import pytest
from test_operations import initial

from noticebridge import publish
from noticebridge.engine import ContractError, canonical
from noticebridge.operations import read_archive, sha, verify_edition


def test_archive_hash_and_parsing_consume_the_same_observed_bytes(tmp_path, monkeypatch):
    data, _, _ = initial(tmp_path)
    index, before = read_archive(data)
    target = data / index["captures"][0]["path"]
    changed = json.loads(target.read_bytes())
    changed["records"][0]["title"] = "Replacement after the fingerprint read"
    replacement = canonical(changed)
    original_open = Path.open
    read_count = 0

    @contextmanager
    def swap_after_first_read(path, mode="r", *args, **kwargs):
        nonlocal read_count
        with original_open(path, mode, *args, **kwargs) as handle:
            yield handle
        if path == target and "r" in mode:
            read_count += 1
            if read_count == 1:
                with original_open(target, "wb") as handle:
                    handle.write(replacement)

    monkeypatch.setattr(Path, "open", swap_after_first_read)
    _, consumed = read_archive(data)
    assert consumed == before, "A different payload was parsed under the old fingerprint"
    assert read_count == 1
    with pytest.raises(ContractError, match="hash mismatch"):
        read_archive(data)


def test_json_read_enforces_the_byte_budget_at_the_read_boundary(tmp_path, monkeypatch):
    target = tmp_path / "large.json"
    target.write_bytes(b'{"safe":true}' + b" " * 100)
    monkeypatch.setattr(publish, "MAX_JSON_BYTES", 64, raising=False)
    with pytest.raises(ContractError, match="bound"):
        publish.read_json(target)


@pytest.mark.parametrize("raw", [b'{"a":1e309}', b'{"a":-1e309}', b"[]", b"null"])
def test_unusable_numeric_values_and_nonobject_roots_are_refused(tmp_path, raw):
    target = tmp_path / "invalid.json"
    target.write_bytes(raw)
    with pytest.raises(ContractError):
        publish.read_json(target)


def test_rehashed_operations_cannot_invent_remaining_archive_capacity(tmp_path):
    data, web, _ = initial(tmp_path)
    pointer = json.loads((web / "current.json").read_bytes())
    operations = json.loads((web / pointer["operations"]["path"]).read_bytes())
    operations["archive_capacity"] = {"maximum": 100, "remaining": 100}
    raw = canonical(operations)
    fingerprint = sha(raw)
    path = f"releases/{fingerprint}.json"
    (web / path).write_bytes(raw)
    pointer["operations"] = {"path": path, "sha256": fingerprint}
    with pytest.raises(ContractError, match="capacity"):
        verify_edition(data, web, pointer)
