"""Hand-computed contract and change-history counterexamples; all data synthetic."""

from copy import deepcopy

import pytest

from noticebridge.engine import ContractError, canonical, compile_release, validate_release


def notice(number="100-2026", **changes):
    return {
        "notice_id": number,
        "title": "Data platform services",
        "buyer": "Synthetic municipality",
        "countries": ["DEU"],
        "cpv_codes": ["72000000"],
        "publication_date": "2026-11-12",
        "deadline": "2026-12-01",
        "notice_type": "cn-standard",
        "previous_notice_ids": [],
        "source_url": f"https://ted.europa.eu/en/notice/-/detail/{number}",
        "scope": "primary",
        **changes,
    }


def snapshot(*records, captured_at="2026-11-15T12:00:00Z"):
    return {
        "schema_version": 1,
        "captured_at": captured_at,
        "source": {
            "name": "TED",
            "scope": "Synthetic contract fixture; not a captured TED response",
            "query": "synthetic fixture",
            "coverage": {
                "bounded": True,
                "selected_count": len(
                    {r["notice_id"] for r in records if r.get("scope", "primary") == "primary"}
                ),
                "total_matching": len(
                    {r["notice_id"] for r in records if r.get("scope", "primary") == "primary"}
                ),
                "complete_for_selection": True,
                "description": "Hand-written synthetic fixture",
            },
        },
        "records": list(records),
    }


def by_id(release):
    return {n["id"]: n for n in release["notices"]}


def test_explicit_change_reconciles_to_hand_written_expected_fields():
    original = notice(scope="context")
    corrected = notice(
        "101-2026",
        publication_date="2026-11-13",
        previous_notice_ids=["100-2026"],
        deadline="2026-12-15",
        title="Data platform and migration services",
    )
    release = compile_release(snapshot(original, corrected))
    correction = by_id(release)["101-2026"]
    assert correction["comparison"] == {
        "status": "compared",
        "parent_id": "100-2026",
        "parent_url": "https://ted.europa.eu/en/notice/-/detail/100-2026",
        "missing_parent_ids": [],
        "changes": [
            {
                "field": "title",
                "label": "Notice title",
                "before": "Data platform services",
                "after": "Data platform and migration services",
            },
            {
                "field": "deadline",
                "label": "Earliest reported lot deadline",
                "before": "2026-12-01",
                "after": "2026-12-15",
            },
            {
                "field": "deadline_dates",
                "label": "All reported lot deadline dates (unmapped to lots)",
                "before": ["2026-12-01"],
                "after": ["2026-12-15"],
            },
        ],
    }
    assert release["summary"] == {
        "notice_count": 2,
        "primary_count": 1,
        "context_count": 1,
        "retained_count": 0,
        "root_count": 1,
        "linked_count": 1,
        "unresolved_count": 0,
        "changed_count": 1,
        "country_count": 1,
        "duplicate_deliveries": 0,
    }
    assert by_id(release)["100-2026"]["has_known_successor"] is True
    assert correction["has_known_successor"] is False


def test_missing_parent_and_ambiguous_parent_never_get_invented_diffs():
    missing = notice("101-2026", previous_notice_ids=["opaque-uuid-version-01"])
    ambiguous = notice("102-2026", previous_notice_ids=["100-2026", "101-2026"])
    result = by_id(compile_release(snapshot(notice(), missing, ambiguous)))
    assert result["101-2026"]["comparison"]["status"] == "missing_parent"
    assert result["101-2026"]["comparison"]["missing_parent_ids"] == ["opaque-uuid-version-01"]
    assert result["102-2026"]["comparison"]["status"] == "ambiguous_parent"
    assert result["101-2026"]["comparison"]["changes"] == []
    assert result["102-2026"]["comparison"]["changes"] == []


def test_procedure_predecessor_does_not_become_a_correction():
    record = notice("102-2026", previous_notice_id_proc="100-2026")
    result = by_id(compile_release(snapshot(notice(), record)))
    assert result["102-2026"]["comparison"]["status"] == "root"
    assert result["100-2026"]["has_known_successor"] is False


def test_unknown_deadline_is_not_zero_or_closed():
    release = compile_release(snapshot(notice(deadline=None)))
    assert release["notices"][0]["deadline"] is None
    assert "deadline_status" not in release["notices"][0]


def test_null_to_known_is_an_explicit_observed_change():
    release = compile_release(
        snapshot(notice(deadline=None), notice("101-2026", previous_notice_ids=["100-2026"]))
    )
    assert by_id(release)["101-2026"]["comparison"]["changes"] == [
        {
            "field": "deadline",
            "label": "Earliest reported lot deadline",
            "before": None,
            "after": "2026-12-01",
        },
        {
            "field": "deadline_dates",
            "label": "All reported lot deadline dates (unmapped to lots)",
            "before": [],
            "after": ["2026-12-01"],
        },
    ]


def test_non_earliest_lot_deadline_change_is_visible():
    original = notice(deadline_dates=["2026-12-01", "2026-12-10"])
    corrected = notice(
        "101-2026",
        previous_notice_ids=["100-2026"],
        deadline_dates=["2026-12-01", "2026-12-20"],
    )
    changes = by_id(compile_release(snapshot(original, corrected)))["101-2026"]["comparison"][
        "changes"
    ]
    assert changes == [
        {
            "field": "deadline_dates",
            "label": "All reported lot deadline dates (unmapped to lots)",
            "before": ["2026-12-01", "2026-12-10"],
            "after": ["2026-12-01", "2026-12-20"],
        }
    ]


def test_uuid_parent_resolves_later_without_rewriting_child_identity():
    uuid = "642c0588-c3e8-42fd-ab38-a32219067f0b"
    child = notice(
        "101-2026",
        previous_notice_ids=[uuid + "-01"],
        source_refs={
            "correction_pointer": uuid + "-01",
            "notice_identifier": "child-id",
            "notice_version": 1,
        },
    )
    first = compile_release(snapshot(child))
    original_hash = first["notices"][0]["content_sha256"]
    parent = notice(
        source_refs={"notice_identifier": uuid, "notice_version": 1, "correction_pointer": None}
    )
    # The collector's convenience resolution changes, but the raw correction pointer does not.
    resolved_child = {**child, "previous_notice_ids": ["100-2026"]}
    later = compile_release(
        snapshot(parent, resolved_child, captured_at="2026-11-16T12:00:00Z"), first
    )
    row = by_id(later)["101-2026"]
    assert row["content_sha256"] == original_hash
    assert row["first_seen_at"] == "2026-11-15T12:00:00Z"
    assert row["comparison"]["parent_id"] == "100-2026"
    assert row["comparison"]["status"] == "compared"
    assert row["correction_refs"] == [uuid + "-01"]


def test_retained_uuid_orphan_resolves_without_redelivery_of_child():
    child = notice("101-2026", source_refs={"correction_pointer": "known-parent-01"})
    first = compile_release(snapshot(child))
    parent = notice(source_refs={"notice_identifier": "known-parent", "notice_version": 1})
    later = compile_release(snapshot(parent, captured_at="2026-11-16T12:00:00Z"), first)
    row = by_id(later)["101-2026"]
    assert row["comparison"]["parent_id"] == "100-2026"
    assert row["scope"] == "retained"
    assert row["first_seen_at"] == row["last_seen_at"] == "2026-11-15T12:00:00Z"


def test_multiple_observed_alias_candidates_remain_ambiguous():
    first = notice(source_refs={"notice_identifier": "shared-parent", "notice_version": 1})
    second = notice(
        "102-2026", source_refs={"notice_identifier": "shared-parent", "notice_version": 1}
    )
    child = notice("103-2026", source_refs={"correction_pointer": "shared-parent-01"})
    result = by_id(compile_release(snapshot(first, second, child)))["103-2026"]
    assert result["comparison"]["status"] == "ambiguous_parent"
    assert result["comparison"]["changes"] == []


def test_same_identity_conflict_is_rejected():
    with pytest.raises(ContractError, match="Conflicting content"):
        compile_release(
            snapshot(notice(), notice(title="Different content under the same publication ID"))
        )


def test_identical_retransmission_collapses_without_join_multiplication():
    release = compile_release(snapshot(notice(), notice()))
    assert release["summary"]["notice_count"] == 1
    assert release["summary"]["duplicate_deliveries"] == 1


def test_row_permutation_produces_identical_release_bytes():
    records = [
        notice(),
        notice("101-2026", previous_notice_ids=["100-2026"]),
        notice("102-2026", countries=["PRT"]),
    ]
    assert canonical(compile_release(snapshot(*records))) == canonical(
        compile_release(snapshot(*reversed(records)))
    )


def test_replay_is_byte_identical_including_capture_history():
    source = snapshot(notice(), notice("101-2026"))
    first = compile_release(source)
    assert canonical(compile_release(source, first)) == canonical(first)


def test_new_selection_retains_history_and_resolves_previous_orphan():
    initial = compile_release(snapshot(notice("101-2026", previous_notice_ids=["100-2026"])))
    later = compile_release(snapshot(notice(), captured_at="2026-11-16T12:00:00Z"), initial)
    rows = by_id(later)
    assert len(rows) == 2
    assert rows["101-2026"]["scope"] == "retained"
    assert rows["101-2026"]["comparison"]["status"] == "compared"
    assert (
        rows["101-2026"]["first_seen_at"]
        == rows["101-2026"]["last_seen_at"]
        == "2026-11-15T12:00:00Z"
    )
    assert rows["100-2026"]["first_seen_at"] == "2026-11-16T12:00:00Z"


def test_observation_absence_is_not_withdrawal():
    previous = compile_release(snapshot(notice()))
    later = compile_release(snapshot(captured_at="2026-11-16T12:00:00Z"), previous)
    assert later["summary"]["retained_count"] == 1
    assert "withdrawn" not in later["notices"][0]


def test_immutable_published_identity_cannot_be_rewritten():
    previous = compile_release(snapshot(notice()))
    with pytest.raises(ContractError, match="Published identity"):
        compile_release(
            snapshot(notice(deadline="2026-12-02"), captured_at="2026-11-16T12:00:00Z"), previous
        )


def test_older_capture_cannot_erase_newer_observation():
    previous = compile_release(snapshot(notice(), captured_at="2026-11-16T12:00:00Z"))
    with pytest.raises(ContractError, match="older capture"):
        compile_release(snapshot(notice()), previous)


@pytest.mark.parametrize(
    "change",
    [
        {"complete_for_selection": False},
        {"selected_count": 2},
        {"total_matching": 0},
        {"total_matching": 2},
        {"total_matching": None},
        {"selected_count": True},
    ],
)
def test_coverage_counterexamples_fail_closed(change):
    source = snapshot(notice())
    source["source"]["coverage"].update(change)
    with pytest.raises(ContractError):
        compile_release(source)


@pytest.mark.parametrize(
    "changes",
    [
        {"source_url": "javascript:alert(1)"},
        {"source_url": "https://ted.europa.eu.evil.test/en/notice/-/detail/100-2026"},
        {"source_url": "https://ted.europa.eu/en/notice/-/detail/999-2026"},
        {"source_url": "https://ted.europa.eu/en/notice/-/detail/100-2026?token=private"},
        {"publication_date": "2026-02-31"},
        {"cpv_codes": ["72-not-a-code"]},
        {"countries": ["Germany"]},
        {"previous_notice_ids": ["100-2026"]},
    ],
)
def test_invalid_notice_contract(changes):
    with pytest.raises(ContractError):
        compile_release(snapshot(notice(**changes)))


def test_cross_record_cycle_and_future_parent_are_rejected():
    with pytest.raises(ContractError, match="Cyclic"):
        compile_release(
            snapshot(
                notice(previous_notice_ids=["101-2026"]),
                notice("101-2026", previous_notice_ids=["100-2026"]),
            )
        )
    with pytest.raises(ContractError, match="predates"):
        compile_release(
            snapshot(
                notice(publication_date="2026-11-14"),
                notice("101-2026", previous_notice_ids=["100-2026"]),
            )
        )


def test_fit_is_a_transparent_rule_tally_not_probability():
    row = compile_release(snapshot(notice()))["notices"][0]
    assert row["fit"]["score"] == 3
    assert [item["key"] for item in row["fit"]["criteria"] if item["matched"]] == [
        "service",
        "country",
        "title",
    ]
    no_match = compile_release(
        snapshot(notice(title="Road repairs", countries=["ESP"], cpv_codes=["45000000"]))
    )["notices"][0]
    assert no_match["fit"]["score"] == 0
    assert no_match["fit"]["reasons"] == []


def test_public_output_uses_whitelisted_fields_only():
    source = snapshot(
        notice(
            contact_email="private@example.test",
            personal_phone="+123456",
            raw_contact={"name": "Synthetic private person"},
        )
    )
    rendered = canonical(compile_release(source)).decode()
    assert "private@example.test" not in rendered
    assert "+123456" not in rendered
    assert "Synthetic private person" not in rendered


def test_corrupted_release_cannot_be_used_as_history():
    previous = compile_release(snapshot(notice()))
    changed = deepcopy(previous)
    changed["notices"][0]["title"] = "Undetected corruption would be bad"
    with pytest.raises(ContractError, match="fingerprint"):
        validate_release(changed)
