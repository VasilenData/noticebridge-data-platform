"""Hand-computed historical replay and promotion counterexamples; synthetic fixtures."""

import json
from copy import deepcopy

import pytest
from test_engine import notice, snapshot

from noticebridge.engine import ContractError, canonical, compile_release
from noticebridge.operations import import_capture, publish_edition, read_archive, verify_edition
from noticebridge.publish import writer_lock


def write_capture(tmp_path, name, records, clock):
    path = tmp_path / name
    path.write_bytes(canonical(snapshot(*records, captured_at=clock)))
    return path


def initial(tmp_path):
    data, web = tmp_path / "data", tmp_path / "web"
    first = write_capture(tmp_path, "first.json", [notice()], "2026-11-15T10:00:00Z")
    import_capture(data, first, "2026-11-12", "bootstrap")
    publish_edition(data, web)
    return data, web, first


def next_capture(tmp_path, data):
    second = write_capture(
        tmp_path,
        "second.json",
        [notice("101-2026", publication_date="2026-11-13", previous_notice_ids=["100-2026"])],
        "2026-11-15T11:00:00Z",
    )
    import_capture(data, second, "2026-11-13", "backfill")
    return second


def test_full_replay_matches_incremental_with_untouched_history(tmp_path):
    data, web, first = initial(tmp_path)
    before_pointer = (web / "current.json").read_bytes()
    second = next_capture(tmp_path, data)
    result = publish_edition(data, web)
    assert result["notices"] == 2
    pointer = json.loads((web / "current.json").read_bytes())
    actual = (web / pointer["release"]["path"]).read_bytes()
    expected = compile_release(
        json.loads(second.read_bytes()), compile_release(json.loads(first.read_bytes()))
    )
    assert actual == canonical(expected)
    old_pointer = json.loads(before_pointer)
    assert (web / old_pointer["release"]["path"]).exists()
    old = {r["id"]: r for r in json.loads(actual)["notices"]}["100-2026"]
    assert old["first_seen_at"] == old["last_seen_at"] == "2026-11-15T10:00:00Z"
    assert old["scope"] == "retained"
    assert verify_edition(data, web)["replay_from_empty"] is True


def test_missing_historical_source_cannot_be_proved_from_current_output(tmp_path):
    data, web, _ = initial(tmp_path)
    next_capture(tmp_path, data)
    publish_edition(data, web)
    index, _ = read_archive(data)
    (data / index["captures"][0]["path"]).unlink()
    with pytest.raises(OSError):
        verify_edition(data, web)


def test_modified_historical_source_is_rejected(tmp_path):
    data, web, _ = initial(tmp_path)
    index, _ = read_archive(data)
    target = data / index["captures"][0]["path"]
    target.write_bytes(target.read_bytes().replace(b"Data platform", b"Fake platform"))
    with pytest.raises(ContractError, match="hash mismatch"):
        verify_edition(data, web)


def test_same_frozen_capture_and_build_are_idempotent(tmp_path):
    data, web, first = initial(tmp_path)
    before = (web / "current.json").read_bytes()
    assert import_capture(data, first, "2026-11-12", "bootstrap")["status"] == "unchanged"
    assert publish_edition(data, web)["status"] == "unchanged"
    assert before == (web / "current.json").read_bytes()


def test_interrupted_promotion_keeps_previous_complete_pair(tmp_path):
    data, web, _ = initial(tmp_path)
    before = (web / "current.json").read_bytes()
    old = json.loads(before)
    original = {key: (web / old[key]["path"]).read_bytes() for key in ("release", "operations")}
    next_capture(tmp_path, data)

    def interrupt(pointer):
        assert all((web / pointer[key]["path"]).exists() for key in ("release", "operations"))
        raise RuntimeError("Synthetic interruption after staging, before pointer replace")

    with pytest.raises(RuntimeError):
        publish_edition(data, web, before_promote=interrupt)
    assert (web / "current.json").read_bytes() == before
    assert all((web / old[k]["path"]).read_bytes() == v for k, v in original.items())
    assert publish_edition(data, web)["status"] == "published"


def test_competing_publisher_is_refused(tmp_path):
    data, web, _ = initial(tmp_path)
    with writer_lock(web / "current.json"):
        with pytest.raises(ContractError, match="Another publisher"):
            publish_edition(data, web)


@pytest.mark.parametrize("damage", ["clock", "path", "duplicate", "day"])
def test_index_damage_is_rejected(tmp_path, damage):
    data, _, _ = initial(tmp_path)
    index, _ = read_archive(data)
    entry = index["captures"][0]
    if damage == "clock":
        entry["captured_at"] = "2026-11-15T00:00:00Z"
    elif damage == "path":
        entry["path"] = "../outside.json"
    elif damage == "duplicate":
        index["captures"].append(deepcopy(entry))
    else:
        entry["publication_day"] = "2026-11-11"
    (data / "captures.json").write_bytes(canonical(index))
    with pytest.raises(ContractError):
        read_archive(data)


def test_backfill_earlier_publication_date_uses_actual_later_observation_time(tmp_path):
    data, web, _ = initial(tmp_path)
    past = write_capture(
        tmp_path,
        "past.json",
        [notice("99-2026", publication_date="2026-11-09")],
        "2026-11-15T12:00:00Z",
    )
    import_capture(data, past, "2026-11-09", "backfill")
    publish_edition(data, web)
    pointer = json.loads((web / "current.json").read_bytes())
    rows = json.loads((web / pointer["release"]["path"]).read_bytes())["notices"]
    assert next(r for r in rows if r["id"] == "99-2026")["first_seen_at"] == "2026-11-15T12:00:00Z"


def test_retrograde_capture_does_not_replace_index_or_pointer(tmp_path):
    data, web, _ = initial(tmp_path)
    old_index = (data / "captures.json").read_bytes()
    old_pointer = (web / "current.json").read_bytes()
    past = write_capture(tmp_path, "past.json", [notice()], "2026-11-15T09:00:00Z")
    with pytest.raises(ContractError, match="regress"):
        import_capture(data, past, "2026-11-12", "refresh")
    assert (data / "captures.json").read_bytes() == old_index
    assert (web / "current.json").read_bytes() == old_pointer
