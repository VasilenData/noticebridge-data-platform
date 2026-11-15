"""Collect an explicit, bounded TED query and limited correction context.

No credentials, contact fields, or unrestricted crawling. A successful collection
means complete pagination of the selected query, not coverage of all procurement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ENDPOINT = "https://api.ted.europa.eu/v3/notices/search"
FIELDS = [
    "publication-number",
    "publication-date",
    "notice-title",
    "buyer-name",
    "organisation-country-buyer",
    "classification-cpv",
    "deadline-receipt-tender-date-lot",
    "notice-type",
    "notice-identifier",
    "notice-version",
    "change-notice-version-identifier",
    "previous-notice-id-proc",
    "modification-previous-notice-identifier",
]
PUB_ID = re.compile(r"^\d{1,8}-\d{4}$")
UUID_VERSION = re.compile(r"^([a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})-(\d+)$", re.I)
MAX_RESPONSE_BYTES = 8_000_000
MAX_PRIMARY = 1000
MAX_CONTEXT = 160
PAGE_SIZE = 100
MAX_RETRY_WAIT = 10


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def retry_after_seconds(hint: str | None, fallback: int) -> int:
    """Honor both HTTP Retry-After forms, without exceeding the wait budget."""
    if not hint:
        return fallback
    hint = hint.strip()
    if hint.isdigit():
        wait = int(hint)
    else:
        try:
            retry_at = parsedate_to_datetime(hint)
            if retry_at.tzinfo is None:
                raise ValueError("Retry-After date needs an explicit time zone")
            wait = max(0, math.ceil((retry_at - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError("Invalid server Retry-After instruction") from exc
    if wait > MAX_RETRY_WAIT:
        raise RuntimeError("Server retry instruction exceeds the collection budget")
    return wait


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_url(request: Request, attempts: list[dict]) -> bytes:
    """Bounded retries; a failed call never replaces the last source snapshot."""
    for attempt in range(3):
        started = time.monotonic()
        observed_at = utc_now()
        try:
            with urlopen(request, timeout=20) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ValueError("Source response exceeds the collection limit")
                attempts.append(
                    {
                        "url": request.full_url,
                        "attempt": attempt + 1,
                        "status": response.status,
                        "bytes": len(body),
                        "sha256": sha(body),
                        "observed_at_utc": observed_at,
                        "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                    }
                )
                return body
        except HTTPError as exc:
            entry = {
                "url": request.full_url,
                "attempt": attempt + 1,
                "status": exc.code,
                "observed_at_utc": observed_at,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            }
            attempts.append(entry)
            retryable = exc.code in {408, 429, 500, 502, 503, 504}
            if not retryable or attempt == 2:
                raise
            wait = retry_after_seconds(exc.headers.get("Retry-After"), 2**attempt)
            entry["retry_wait_seconds"] = wait
            time.sleep(wait)
        except (TimeoutError, ConnectionError, URLError) as exc:
            attempts.append(
                {
                    "url": request.full_url,
                    "attempt": attempt + 1,
                    "error": type(exc).__name__,
                    "observed_at_utc": observed_at,
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                    "retry_wait_seconds": 2**attempt if attempt < 2 else None,
                }
            )
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def search(query: str, evidence: list[dict], *, limit: int = MAX_PRIMARY) -> list[dict]:
    """Use TED's point-in-time iteration; require the final empty page."""
    token = None
    seen_tokens: set[str] = set()
    records: list[dict] = []
    total = None
    page = 0
    while True:
        page += 1
        body: dict[str, Any] = {
            "query": query,
            "fields": FIELDS,
            "limit": PAGE_SIZE,
            "scope": "ALL",
            "paginationMode": "ITERATION",
            "onlyLatestVersions": False,
        }
        if token:
            body["iterationNextToken"] = token
        attempts: list[dict] = []
        raw = read_url(
            Request(
                ENDPOINT,
                data=canonical(body),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "NoticeBridge-portfolio-public-data/0.1",
                },
            ),
            attempts,
        )
        response = json.loads(raw)
        if response.get("timedOut"):
            raise ValueError("TED reported a timed-out partial search")
        batch = response.get("notices")
        if (
            not isinstance(batch, list)
            or type(response.get("totalNoticeCount")) is not int
            or response["totalNoticeCount"] < 0
            or any(
                not isinstance(item, dict)
                or not isinstance(item.get("publication-number"), str)
                or not PUB_ID.fullmatch(item["publication-number"])
                for item in batch
            )
        ):
            raise ValueError("TED search response does not satisfy the source contract")
        if total is None:
            total = response["totalNoticeCount"]
            if total > limit:
                raise ValueError(
                    f"Query population {total} exceeds bounded limit {limit}; narrow the query"
                )
        if total != response["totalNoticeCount"]:
            raise ValueError("Population changed within the point-in-time search")
        evidence.append(
            {
                "query": query,
                "page": page,
                "pagination_mode": "ITERATION",
                "count": len(batch),
                "total_matching": total,
                "response_sha256": sha(raw),
                "request_sha256": sha(canonical(body)),
                "attempts": attempts,
            }
        )
        if not batch:
            if len(records) != total:
                raise ValueError("Terminal page does not reconcile to the query population")
            identifiers = [n.get("publication-number") for n in records]
            if len(set(identifiers)) != len(identifiers):
                raise ValueError("Duplicate publication identifier in the query result")
            return records
        records.extend(batch)
        if len(records) > total:
            raise ValueError("Page rows exceed the reported query population")
        if len(records) > limit or page > 20:
            raise ValueError("Bounded query pagination exceeded")
        new_token = response.get("iterationNextToken")
        if not isinstance(new_token, str) or not new_token or new_token in seen_tokens:
            raise ValueError("TED pagination token missing or repeated")
        seen_tokens.add(new_token)
        token = new_token


def text_choice(value: Any, fallback: str = "Not reported") -> str:
    if not isinstance(value, dict) or not value:
        return fallback
    key = "eng" if "eng" in value else sorted(value)[0]
    selected = value[key]
    if isinstance(selected, list):
        return " / ".join(str(x) for x in selected)
    return str(selected)


def calendar_date(value: str | None) -> str | None:
    if not value:
        return None
    # TED dates can contain a timezone suffix without an hour. Calendar dates
    # remain local dates; this does not pretend they are midnight UTC instants.
    result = value[:10]
    date.fromisoformat(result)
    return result


def pointer_query(pointer: str) -> str | None:
    if PUB_ID.fullmatch(pointer):
        return f'publication-number = "{pointer}"'
    match = UUID_VERSION.fullmatch(pointer)
    if match:
        return (
            f'(notice-identifier = "{match.group(1)}" AND notice-version = {int(match.group(2))})'
        )
    return None


def known_pointers(raws: dict[str, dict]) -> dict[str, str]:
    result: dict[str, str] = {}

    def add(alias: str, publication: str) -> None:
        if alias in result and result[alias] != publication:
            raise ValueError(f"Ambiguous notice/version alias: {alias}")
        result[alias] = publication

    for publication, raw in raws.items():
        add(publication, publication)
        identifier, version = raw.get("notice-identifier"), raw.get("notice-version")
        if identifier and version is not None:
            add(f"{identifier}-{int(version):02d}", publication)
            add(f"{identifier}-{int(version)}", publication)
    return result


def normalize(raw: dict, scope: str, lookup: dict[str, str]) -> dict:
    publication = raw.get("publication-number", "")
    if not PUB_ID.fullmatch(publication):
        raise ValueError("Unexpected TED publication identifier")
    pointer = raw.get("change-notice-version-identifier")
    deadlines = sorted(
        {calendar_date(x) for x in raw.get("deadline-receipt-tender-date-lot", []) if x}
    )
    selected = {key: raw[key] for key in FIELDS if key in raw}
    return {
        "notice_id": publication,
        "publication_date": calendar_date(raw.get("publication-date")),
        "title": text_choice(raw.get("notice-title")),
        "buyer": text_choice(raw.get("buyer-name")),
        "countries": sorted(set(raw.get("organisation-country-buyer", []))),
        "cpv_codes": sorted(set(raw.get("classification-cpv", []))),
        "deadline": deadlines[0] if deadlines else None,
        "deadline_dates": deadlines,
        "deadline_label": "Earliest reported lot deadline",
        "notice_type": raw.get("notice-type", "unknown"),
        "previous_notice_ids": [lookup.get(pointer, pointer)] if pointer else [],
        "source_url": f"https://ted.europa.eu/en/notice/-/detail/{publication}",
        "scope": scope,
        "source_hash": sha(canonical(selected)),
        "source_refs": {
            "correction_pointer_field": "change-notice-version-identifier",
            "correction_pointer": pointer,
            "correction_pointer_resolved": bool(pointer and pointer in lookup),
            "procedure_predecessors": raw.get("previous-notice-id-proc", []),
            "contract_modification_predecessors": raw.get(
                "modification-previous-notice-identifier", []
            ),
            "notice_identifier": raw.get("notice-identifier"),
            "notice_version": raw.get("notice-version"),
            "publication_date_raw": raw.get("publication-date"),
            "lot_deadlines_raw": raw.get("deadline-receipt-tender-date-lot", []),
            "selected_fields": selected,
        },
    }


def verify_xml(raw: dict) -> dict:
    """Extract selected identifiers/dates from published XML representations."""
    publication = raw["publication-number"]
    if not PUB_ID.fullmatch(publication):
        raise ValueError("Invalid XML publication identifier")
    url = f"https://ted.europa.eu/en/notice/{publication}/xml"
    attempts: list[dict] = []
    body = read_url(
        Request(url, headers={"User-Agent": "NoticeBridge-portfolio-public-data/0.1"}), attempts
    )
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ValueError("XML external entities are prohibited")
    root = ET.fromstring(body)

    def name(element: ET.Element) -> str:
        return element.tag.rsplit("}", 1)[-1]

    direct = {name(e): e.text for e in root if name(e) in {"ID", "VersionID", "NoticeTypeCode"}}
    pointers = [e.text for e in root.iter() if name(e) == "ChangedNoticeIdentifier"]
    publication_dates = [calendar_date(e.text) for e in root.iter() if name(e) == "PublicationDate"]
    deadlines = sorted(
        {
            calendar_date(e.text)
            for parent in root.iter()
            if name(parent) == "TenderSubmissionDeadlinePeriod"
            for e in parent
            if name(e) == "EndDate" and e.text
        }
    )
    checks = {
        "notice_identifier": direct.get("ID") == raw.get("notice-identifier"),
        "notice_version": int(direct.get("VersionID", -1)) == raw.get("notice-version"),
        "notice_type": direct.get("NoticeTypeCode") == raw.get("notice-type"),
        "publication_date": calendar_date(raw.get("publication-date")) in publication_dates,
        "explicit_correction_pointer": pointers == [raw["change-notice-version-identifier"]],
        "reported_lot_deadlines": deadlines
        == sorted({calendar_date(x) for x in raw.get("deadline-receipt-tender-date-lot", [])}),
    }
    if not all(checks.values()):
        raise ValueError(f"API/XML reconciliation failed for {publication}: {checks}")
    return {
        "notice_id": publication,
        "url": url,
        "sha256": sha(body),
        "bytes": len(body),
        "checks": checks,
        "selected_xml_values": {
            **direct,
            "correction_pointers": pointers,
            "publication_dates": publication_dates,
            "lot_deadlines": deadlines,
        },
        "attempts": attempts,
        "raw_xml_published": False,
        "scope": (
            "Selected identifier/date fields only; "
            "not a complete semantic validation of the notice."
        ),
    }


def collect(query: str, *, context_depth: int = 2) -> dict:
    if type(context_depth) is not int or not 0 <= context_depth <= 4:
        raise ValueError("Context depth must be an integer between zero and four")
    captured_at = utc_now()
    requests: list[dict] = []
    primary = search(query, requests)
    all_raw = {n["publication-number"]: n for n in primary}
    primary_ids = set(all_raw)
    attempted: set[str] = set()
    unresolved: list[str] = []
    for _ in range(context_depth):
        lookup = known_pointers(all_raw)
        pointers = sorted(
            {
                n.get("change-notice-version-identifier")
                for n in all_raw.values()
                if n.get("change-notice-version-identifier")
                and n.get("change-notice-version-identifier") not in lookup
            }
        )
        pending = [p for p in pointers if p not in attempted and pointer_query(p)]
        if not pending:
            break
        for start in range(0, len(pending), 12):
            chunk = pending[start : start + 12]
            attempted.update(chunk)
            context = search(
                " OR ".join(pointer_query(p) for p in chunk), requests, limit=MAX_CONTEXT
            )
            for raw in context:
                publication = raw["publication-number"]
                if publication in all_raw:
                    previous = {
                        key: all_raw[publication][key]
                        for key in FIELDS
                        if key in all_raw[publication]
                    }
                    candidate = {key: raw[key] for key in FIELDS if key in raw}
                    if canonical(previous) != canonical(candidate):
                        raise ValueError(
                            f"Conflicting publication contents during context lookup: {publication}"
                        )
                else:
                    all_raw[publication] = raw
            if len(all_raw) - len(primary) > MAX_CONTEXT:
                raise ValueError("Context collection exceeded its explicit bound")
    lookup = known_pointers(all_raw)
    unresolved = sorted(
        {
            n.get("change-notice-version-identifier")
            for n in all_raw.values()
            if n.get("change-notice-version-identifier")
            and n.get("change-notice-version-identifier") not in lookup
        }
    )
    xml_candidates = [raw for raw in primary if raw.get("change-notice-version-identifier")][:5]
    xml_checks = [verify_xml(raw) for raw in xml_candidates]
    records = [
        normalize(raw, "primary" if identifier in primary_ids else "context", lookup)
        for identifier, raw in sorted(all_raw.items())
    ]
    completed_at = utc_now()
    return {
        "schema_version": 1,
        "captured_at": captured_at,
        "source": {
            "name": "TED",
            "endpoint": ENDPOINT,
            "scope": (
                "Published TED notices matching the explicit date and CPV query, "
                "plus bounded correction context"
            ),
            "query": query,
            "fields": FIELDS,
            "coverage": {
                "bounded": True,
                "selected_count": len(primary),
                "total_matching": len(primary),
                "complete_for_selection": True,
                "context_count": len(records) - len(primary),
                "context_depth_limit": context_depth,
                "context_record_limit": MAX_CONTEXT,
                "unresolved_correction_references": unresolved,
                "description": (
                    "All pages of the stated primary query reconciled to TED's reported "
                    "population, including the terminal empty page. Context follows explicit "
                    f"correction pointers for at most {context_depth} hops; missing older parents "
                    "remain visible. This is not all TED notices, all IT opportunities, "
                    "or a complete procedure history."
                ),
            },
        },
        "records": records,
        "evidence": {
            "completed_at": completed_at,
            "collector_source_sha256": sha(Path(__file__).read_bytes().replace(b"\r\n", b"\n")),
            "collector_hash_scope": "LF-normalized UTF-8 bytes of sources/collect.py",
            "source_kind": "real_public_TED_notices",
            "search_requests": requests,
            "api_xml_checks": xml_checks,
            "publication_id_set_sha256": sha(canonical(sorted(primary_ids))),
            "country_semantics": (
                "ISO 3166-1 alpha-3 buyer organization countries; "
                "not necessarily place of performance or eligibility"
            ),
            "deadline_semantics": (
                "Earliest calendar date among reported tender-receipt lot dates; "
                "no implied exact UTC instant, open/closed status, or universal lot deadline"
            ),
            "title_language": (
                "English display title where supplied by TED; procurement title content "
                "can remain in the source language"
            ),
            "correction_semantics": (
                "Only change-notice-version-identifier creates a correction edge. "
                "Procedure and contract-modification predecessors are retained separately "
                "and never converted into correction edges."
            ),
            "privacy": (
                "Only the enumerated identifier, organization, classification and date fields "
                "are requested and retained. No email, phone, street address or person/contact "
                "fields. Original XML is hashed and discarded after extracting "
                "selected identifiers/dates."
            ),
            "limitations": [
                "A single collection, not sustained operation",
                "No supplier eligibility determination",
                "No commercial adoption or procurement outcome claim",
                "No entity matching inferred from organization names",
                "Primary population is bounded by one publication day and CPV hierarchy",
                f"API/XML comparison covers {len(xml_checks)} selected notices "
                "and six identifier/date checks each",
            ],
        },
    }


def collect_day(publication_day: date | str, *, context_depth: int = 2) -> dict:
    """Collect one explicit publication partition and reject misplaced primary rows."""
    if isinstance(publication_day, str):
        publication_day = date.fromisoformat(publication_day)
    if type(publication_day) is not date:
        raise ValueError("Publication day must be an ISO calendar date")
    query = f"publication-date = {publication_day:%Y%m%d} AND classification-cpv = 72000000"
    snapshot = collect(query, context_depth=context_depth)
    expected = publication_day.isoformat()
    if any(
        row["scope"] == "primary" and row["publication_date"] != expected
        for row in snapshot["records"]
    ):
        raise ValueError("Primary record falls outside the requested publication-date partition")
    snapshot["source"]["publication_date"] = expected
    return snapshot


def atomic_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=".source-stage-", suffix=".json", delete=False
    ) as f:
        staged = Path(f.name)
        f.write(json.dumps(value, indent=2, ensure_ascii=False).encode("utf-8") + b"\n")
        f.flush()
        os.fsync(f.fileno())
    try:
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication-date", default="2026-11-13")
    parser.add_argument("--output", type=Path, default=Path("data/source_snapshot.json"))
    args = parser.parse_args()
    snapshot = collect_day(args.publication_date)
    atomic_write(args.output, snapshot)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "captured_at": snapshot["captured_at"],
                "primary": snapshot["source"]["coverage"]["selected_count"],
                "context": snapshot["source"]["coverage"]["context_count"],
                "unresolved": len(
                    snapshot["source"]["coverage"]["unresolved_correction_references"]
                ),
                "xml_checked": len(snapshot["evidence"]["api_xml_checks"]),
            }
        )
    )


if __name__ == "__main__":
    main()
