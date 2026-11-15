"""Network-free correctness checks for TED selection and collection boundaries."""

import io
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from sources import collect as c


def response(notices, total=1, token=None, **extra):
    return json.dumps(
        {"notices": notices, "totalNoticeCount": total, "iterationNextToken": token, **extra}
    ).encode()


def transport(monkeypatch, responses):
    replies = iter(responses)
    seen = []

    def request(req, attempts):
        seen.append(json.loads(req.data))
        return next(replies)

    monkeypatch.setattr(c, "read_url", request)
    return seen


def test_complete_selection_requires_terminal_empty_page(monkeypatch):
    seen = transport(
        monkeypatch,
        [response([{"publication-number": "1-2026"}], token="a"), response([], token="b")],
    )
    evidence = []
    assert c.search("selected query", evidence) == [{"publication-number": "1-2026"}]
    assert seen[0]["paginationMode"] == "ITERATION"
    assert "iterationNextToken" not in seen[0]
    assert seen[1]["iterationNextToken"] == "a"
    assert [x["count"] for x in evidence] == [1, 0]


@pytest.mark.parametrize(
    "first,second,match",
    [
        (response([{"publication-number": "1-2026"}], timedOut=True), None, "timed-out"),
        (
            response([{"publication-number": "1-2026"}], total=2, token="a"),
            response([], total=2),
            "reconcile",
        ),
        (
            response([{"publication-number": "1-2026"}], token="a"),
            response([], total=2),
            "Population changed",
        ),
        (response([{"publication-number": "1-2026"}]), None, "token missing"),
        (
            response(
                [{"publication-number": "1-2026"}, {"publication-number": "1-2026"}],
                total=2,
                token="a",
            ),
            response([], total=2),
            "Duplicate",
        ),
        (response([], total=1001), None, "bounded limit"),
    ],
)
def test_incomplete_or_inconsistent_query_fails_closed(monkeypatch, first, second, match):
    transport(monkeypatch, [first, second])
    with pytest.raises(ValueError, match=match):
        c.search("selected query", [])


def test_ambiguous_uuid_version_cannot_silently_select_a_parent():
    raws = {
        "1-2026": {"notice-identifier": "same", "notice-version": 1},
        "2-2026": {"notice-identifier": "same", "notice-version": 1},
    }
    with pytest.raises(ValueError, match="Ambiguous"):
        c.known_pointers(raws)


def test_only_explicit_corrections_are_edges_and_all_dates_are_retained():
    raw = {
        "publication-number": "1-2026",
        "publication-date": "2026-11-13+01:00",
        "notice-title": {"eng": "Public service"},
        "buyer-name": {"por": ["Public agency"]},
        "classification-cpv": ["72000000", "72000000"],
        "organisation-country-buyer": ["PRT"],
        "notice-type": "cn-standard",
        "deadline-receipt-tender-date-lot": ["2026-12-01Z", "2026-11-25+01:00"],
        "change-notice-version-identifier": "parent-01",
        "previous-notice-id-proc": ["9-2026"],
        "modification-previous-notice-identifier": ["8-2026"],
    }
    actual = c.normalize(raw, "primary", {"parent-01": "2-2026"})
    assert actual["previous_notice_ids"] == ["2-2026"]
    assert actual["deadline"] == "2026-11-25"
    assert actual["deadline_dates"] == ["2026-11-25", "2026-12-01"]
    assert actual["source_refs"]["procedure_predecessors"] == ["9-2026"]
    assert actual["source_refs"]["contract_modification_predecessors"] == ["8-2026"]
    assert actual["publication_date"] == "2026-11-13"
    assert actual["deadline_label"] == "Earliest reported lot deadline"
    assert actual["source_hash"] == c.sha(c.canonical(actual["source_refs"]["selected_fields"]))
    raw.pop("change-notice-version-identifier")
    assert c.normalize(raw, "primary", {})["previous_notice_ids"] == []


def test_unresolved_parent_is_retained_without_inventing_publication_id():
    raw = {
        "publication-number": "1-2026",
        "publication-date": "2026-11-13Z",
        "change-notice-version-identifier": "unresolved-01",
    }
    actual = c.normalize(raw, "context", {})
    assert actual["previous_notice_ids"] == ["unresolved-01"]
    assert actual["source_refs"]["correction_pointer_resolved"] is False


def test_only_well_formed_source_pointers_can_become_queries():
    assert c.pointer_query('1-2026" OR publication-date > 20000101') is None
    assert c.pointer_query("1-2026") == 'publication-number = "1-2026"'
    assert c.pointer_query("642c0588-c3e8-42fd-ab38-a32219067f0b-01").endswith(
        "notice-version = 1)"
    )


class FakeReply(io.BytesIO):
    status = 200


def test_transient_http_wait_is_honored_before_retry(monkeypatch):
    replies = iter(
        [HTTPError(c.ENDPOINT, 503, "temporary", {"Retry-After": "3"}, None), FakeReply(b"ok")]
    )
    waits = []

    def opened(*args, **kwargs):
        value = next(replies)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(c, "urlopen", opened)
    monkeypatch.setattr(c.time, "sleep", waits.append)
    attempts = []
    assert c.read_url(Request(c.ENDPOINT), attempts) == b"ok"
    assert waits == [3]
    assert [x["status"] for x in attempts] == [503, 200]


@pytest.mark.parametrize("status,hint,error", [(403, None, HTTPError), (429, "60", RuntimeError)])
def test_permanent_or_excessive_retry_response_fails_without_retry(
    monkeypatch, status, hint, error
):
    calls = []

    def opened(*args, **kwargs):
        calls.append(1)
        raise HTTPError(c.ENDPOINT, status, "failure", {"Retry-After": hint} if hint else {}, None)

    monkeypatch.setattr(c, "urlopen", opened)
    monkeypatch.setattr(c.time, "sleep", lambda _: pytest.fail("must not wait/retry"))
    with pytest.raises(error):
        c.read_url(Request(c.ENDPOINT), [])
    assert len(calls) == 1


def test_timeout_attempt_count_is_bounded(monkeypatch):
    calls, waits = [], []

    def opened(*args, **kwargs):
        calls.append(kwargs["timeout"])
        raise TimeoutError("synthetic transport timeout")

    monkeypatch.setattr(c, "urlopen", opened)
    monkeypatch.setattr(c.time, "sleep", waits.append)
    with pytest.raises(TimeoutError):
        c.read_url(Request(c.ENDPOINT), [])
    assert calls == [20, 20, 20]
    assert waits == [1, 2]


def test_failed_promotion_preserves_previous_snapshot(monkeypatch, tmp_path):
    target = tmp_path / "source.json"
    target.write_bytes(b"previous valid snapshot")

    def failure(*args):
        raise OSError("simulated publication interruption")

    monkeypatch.setattr(c.os, "replace", failure)
    with pytest.raises(OSError):
        c.atomic_write(target, {"new": "candidate"})
    assert target.read_bytes() == b"previous valid snapshot"
    assert list(tmp_path.glob(".source-stage-*")) == []


def test_partial_source_failure_does_not_touch_published_snapshot(monkeypatch, tmp_path):
    target = tmp_path / "source.json"
    target.write_bytes(b"previous valid snapshot")
    monkeypatch.setattr("sys.argv", ["collect", "--output", str(target)])
    monkeypatch.setattr(
        c, "collect", lambda *a, **kw: (_ for _ in ()).throw(ValueError("timed-out source"))
    )
    with pytest.raises(ValueError, match="timed-out"):
        c.main()
    assert target.read_bytes() == b"previous valid snapshot"


def test_context_cannot_replace_or_hide_changed_publication(monkeypatch, tmp_path):
    target = tmp_path / "source.json"
    target.write_bytes(b"previous valid snapshot")
    primary = {
        "publication-number": "1-2026",
        "publication-date": "2026-11-13Z",
        "deadline-receipt-tender-date-lot": ["2026-11-18Z"],
        "change-notice-version-identifier": "2-2026",
    }
    changed = {**primary, "deadline-receipt-tender-date-lot": ["2026-11-25Z"]}
    parent = {"publication-number": "2-2026", "publication-date": "2026-10-13Z"}
    results = iter([[primary], [changed, parent]])
    monkeypatch.setattr(c, "search", lambda *args, **kwargs: next(results))
    monkeypatch.setattr("sys.argv", ["collect", "--output", str(target)])
    with pytest.raises(ValueError, match="Conflicting publication contents"):
        c.main()
    assert target.read_bytes() == b"previous valid snapshot"


def test_frozen_capture_contains_no_contact_fields():
    snapshot = json.loads(
        (Path(__file__).parents[1] / "data/source_snapshot.json").read_text(encoding="utf-8")
    )
    permitted = set(c.FIELDS)
    for record in snapshot["records"]:
        assert set(record["source_refs"]["selected_fields"]).issubset(permitted)
    assert not any(
        term in field for field in permitted for term in ["email", "person", "tel-", "street"]
    )


@pytest.mark.parametrize(
    "payload",
    [
        response([], total=True),
        response([], total=-1),
        response(["not a notice"], token="a"),
        response([{"publication-number": "not an id"}], token="a"),
        response([{}], token="a"),
    ],
)
def test_malformed_page_contract_cannot_enter_a_capture(monkeypatch, payload):
    transport(monkeypatch, [payload])
    with pytest.raises(ValueError, match="source contract"):
        c.search("selected query", [])


def test_page_cannot_exceed_its_reported_population(monkeypatch):
    transport(monkeypatch, [response([{"publication-number": "1-2026"}], total=0, token="a")])
    with pytest.raises(ValueError, match="exceed the reported"):
        c.search("selected query", [])


def test_retry_after_http_date_is_honored_and_bounded(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(c, "datetime", FixedDateTime)
    assert c.retry_after_seconds("Sun, 15 Nov 2026 12:00:05 GMT", 1) == 5
    assert c.retry_after_seconds("Sun, 15 Nov 2026 11:59:00 GMT", 1) == 0
    with pytest.raises(RuntimeError, match="exceeds"):
        c.retry_after_seconds("Sun, 15 Nov 2026 12:00:11 GMT", 1)
    with pytest.raises(RuntimeError, match="Invalid"):
        c.retry_after_seconds("not a time", 1)


def test_capture_day_checks_partition_without_rejecting_historical_context(monkeypatch):
    def captured(*args, **kwargs):
        return {
            "source": {},
            "records": [
                {"scope": "primary", "publication_date": "2026-11-12"},
                {"scope": "context", "publication_date": "2026-10-01"},
            ],
        }

    monkeypatch.setattr(c, "collect", captured)
    assert c.collect_day("2026-11-12")["source"]["publication_date"] == "2026-11-12"
    with pytest.raises(ValueError, match="outside the requested"):
        c.collect_day("2026-11-11")


@pytest.mark.parametrize("depth", [-1, 5, True, 1.5])
def test_context_budget_is_validated_before_any_request(monkeypatch, depth):
    monkeypatch.setattr(c, "search", lambda *a, **kw: pytest.fail("must not fetch"))
    with pytest.raises(ValueError, match="Context depth"):
        c.collect("selected query", context_depth=depth)
