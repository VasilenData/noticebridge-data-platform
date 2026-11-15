"""Independent archive counterexamples; all notices and observations are synthetic."""

from copy import deepcopy

import pytest
from test_engine import notice, snapshot

from noticebridge.engine import ContractError, canonical
from noticebridge.operations import (
    import_batch,
    import_capture,
    publish_edition,
    replay,
    verify_edition,
)


def source_file(tmp_path, name, *records, captured_at):
    path = tmp_path / name
    path.write_bytes(canonical(snapshot(*records, captured_at=captured_at)))
    return path


def initial_archive(tmp_path):
    data, web = tmp_path / "data", tmp_path / "web"
    first = source_file(tmp_path, "first.json", notice(), captured_at="2026-11-15T12:00:00Z")
    import_capture(data, first, "2026-11-12", "bootstrap")
    publish_edition(data, web)
    return data, web


def test_conflicting_recapture_cannot_poison_the_replayable_archive(tmp_path):
    data, web = initial_archive(tmp_path)
    old_index = (data / "captures.json").read_bytes()
    old_pointer = (web / "current.json").read_bytes()
    conflicting = source_file(
        tmp_path,
        "conflict.json",
        notice(title="A different source title under the same immutable publication ID"),
        captured_at="2026-11-15T13:00:00Z",
    )
    with pytest.raises(ContractError, match="Published identity"):
        import_capture(data, conflicting, "2026-11-12", "refresh")
    assert (data / "captures.json").read_bytes() == old_index
    assert (web / "current.json").read_bytes() == old_pointer
    assert verify_edition(data, web)["replay_from_empty"] is True


def test_later_capture_cannot_create_a_cycle_and_poison_existing_history(tmp_path):
    data, web = tmp_path / "data", tmp_path / "web"
    first = source_file(
        tmp_path,
        "orphan.json",
        notice("100-2026", previous_notice_ids=["101-2026"]),
        captured_at="2026-11-15T12:00:00Z",
    )
    import_capture(data, first, "2026-11-12", "bootstrap")
    publish_edition(data, web)
    old_index = (data / "captures.json").read_bytes()
    cyclic = source_file(
        tmp_path,
        "cyclic.json",
        notice("101-2026", previous_notice_ids=["100-2026"]),
        captured_at="2026-11-15T13:00:00Z",
    )
    with pytest.raises(ContractError, match="Cyclic"):
        import_capture(data, cyclic, "2026-11-12", "backfill")
    assert (data / "captures.json").read_bytes() == old_index
    assert verify_edition(data, web)["status"] == "verified"


def test_replay_rejects_a_missing_historical_source_despite_valid_consumer(tmp_path):
    data, web = initial_archive(tmp_path)
    old_pointer = (web / "current.json").read_bytes()
    archived_source = next((data / "captures").glob("*.json"))
    # This synthetic fixture is disposable. A missing input must not be inferred
    # from the last published consumer output.
    archived_source.unlink()
    with pytest.raises((ContractError, OSError)):
        publish_edition(data, web)
    assert (web / "current.json").read_bytes() == old_pointer


def test_capture_manifest_cannot_backdate_an_observation(tmp_path):
    data, web = initial_archive(tmp_path)
    index, _, _ = replay(data)
    changed = deepcopy(index)
    changed["captures"][0]["captured_at"] = "2025-11-15T12:00:00Z"
    (data / "captures.json").write_bytes(canonical(changed))
    with pytest.raises(ContractError, match="observation time"):
        verify_edition(data, web)


def test_historical_publication_day_can_arrive_in_a_later_observation(tmp_path):
    data, web = initial_archive(tmp_path)
    older_publication = source_file(
        tmp_path,
        "backfill.json",
        notice("99-2026", publication_date="2026-11-10"),
        captured_at="2026-11-15T13:00:00Z",
    )
    import_capture(data, older_publication, "2026-11-10", "backfill")
    publish_edition(data, web)
    _, releases, _ = replay(data)
    rows = {row["id"]: row for row in releases[-1]["notices"]}
    assert rows["99-2026"]["first_seen_at"] == "2026-11-15T13:00:00Z"
    assert rows["100-2026"]["first_seen_at"] == "2026-11-15T12:00:00Z"
    assert verify_edition(data, web)["status"] == "verified"


def test_last_member_of_failed_batch_cannot_commit_earlier_members(tmp_path):
    data, web = initial_archive(tmp_path)
    before_index = (data / "captures.json").read_bytes()
    before_pointer = (web / "current.json").read_bytes()
    valid = source_file(
        tmp_path, "valid.json", notice("101-2026"), captured_at="2026-11-15T13:00:00Z"
    )
    conflict = source_file(
        tmp_path,
        "invalid.json",
        notice(title="Conflicting content late in the batch"),
        captured_at="2026-11-15T14:00:00Z",
    )
    with pytest.raises(ContractError, match="Published identity"):
        import_batch(
            data,
            [(valid, "2026-11-12", "refresh"), (conflict, "2026-11-12", "refresh")],
        )
    assert (data / "captures.json").read_bytes() == before_index
    assert (web / "current.json").read_bytes() == before_pointer
    assert verify_edition(data, web)["notices"] == 1


def test_archive_import_cannot_overtake_a_validated_pointer_promotion(tmp_path):
    data, web = initial_archive(tmp_path)
    second = source_file(
        tmp_path, "second.json", notice("101-2026"), captured_at="2026-11-15T13:00:00Z"
    )
    third = source_file(
        tmp_path, "third.json", notice("102-2026"), captured_at="2026-11-15T14:00:00Z"
    )
    import_capture(data, second, "2026-11-12", "refresh")
    attempts = []

    def competing_import(_pointer):
        # This callback is after candidate verification but before pointer promotion.
        # A successful import here would advance the archive past the verified edition.
        with pytest.raises(ContractError, match="Another publisher"):
            import_capture(data, third, "2026-11-12", "refresh")
        attempts.append("refused at the observed publication boundary")

    assert publish_edition(data, web, before_promote=competing_import)["status"] == "published"
    assert len(attempts) == 1
    assert verify_edition(data, web)["notices"] == 2
    # The same import succeeds once promotion releases the archive lock.
    import_capture(data, third, "2026-11-12", "refresh")
    publish_edition(data, web)
    assert verify_edition(data, web)["notices"] == 3
