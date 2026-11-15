"""Pure, deterministic release compilation. No inferred correction links."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit


class ContractError(ValueError):
    """The source or previous release cannot safely be published."""


FIELDS = (
    "title",
    "buyer",
    "countries",
    "cpv_codes",
    "publication_date",
    "deadline",
    "deadline_dates",
    "deadline_label",
    "type",
    "source_url",
    "correction_refs",
    "notice_identifier",
    "notice_version",
    "source_record_sha256",
)
COMPARE_FIELDS = {
    "title": "Notice title",
    "buyer": "Buyer",
    "countries": "Buyer country",
    "cpv_codes": "Service classification (CPV)",
    "deadline": "Earliest reported lot deadline",
    "deadline_dates": "All reported lot deadline dates (unmapped to lots)",
    "type": "Notice type",
}
MAX_RECORDS = 50_000
DATA_TERMS = re.compile(r"\b(data|analytics|database|warehouse|daten|données|dados)\b", re.I)
TARGET_COUNTRIES = {"PRT", "DEU", "NLD", "GBR", "CHE", "PT", "DE", "NL", "GB", "CH"}


def canonical(value: object) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        + "\n"
    ).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def code_fingerprint() -> str:
    """Normalize text line endings so the checked-out OS does not alter a release."""
    root = Path(__file__).resolve().parent
    items = {
        p.name: p.read_text(encoding="utf-8").replace("\r\n", "\n")
        for p in sorted(root.glob("*.py"))
    }
    return digest(items)


def _text(value: object, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 20_000:
        raise ContractError(f"{field} must be a bounded, non-empty string")
    return value.strip()


def _strings(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 500:
        raise ContractError(f"{field} must be an array of at most 500 strings")
    return sorted({_text(item, field) for item in value})


def _day(value: object, field: str, *, optional: bool = False) -> str | None:
    result = _text(value, field, optional=optional)
    if result is not None:
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", result):
                raise ValueError("not a calendar date")
            date.fromisoformat(result)
        except ValueError as exc:
            raise ContractError(f"{field} must be YYYY-MM-DD, not an inferred instant") from exc
    return result


def _capture_time(value: object) -> str:
    result = _text(value, "captured_at")
    try:
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError("not UTC")
    except ValueError as exc:
        raise ContractError("captured_at must be an explicit UTC timestamp") from exc
    return result


def normalize_record(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise ContractError("Each record must be an object")
    notice_id = _text(raw.get("notice_id"), "notice_id")
    if not re.fullmatch(r"\d{1,8}-\d{4}", notice_id):
        raise ContractError("notice_id must be an actual TED publication identifier")
    url = _text(raw.get("source_url"), "source_url")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "ted.europa.eu"
        or parsed.username
        or parsed.password
    ):
        raise ContractError("source_url must be an HTTPS TED notice link")
    if parsed.path != "/en/notice/-/detail/" + notice_id or parsed.query or parsed.fragment:
        raise ContractError("source_url must identify the same notice without query parameters")
    source_refs = raw.get("source_refs", {})
    if not isinstance(source_refs, dict):
        raise ContractError("source_refs must be an object")
    pointer = source_refs.get("correction_pointer")
    pointer_values = pointer if isinstance(pointer, list) else [pointer] if pointer else []
    correction_refs = raw.get(
        "correction_refs",
        pointer_values
        if "correction_pointer" in source_refs
        else raw.get("previous_notice_ids", []),
    )
    version = raw.get("notice_version", source_refs.get("notice_version"))
    if version is not None and (type(version) is not int or version < 1 or version > 9999):
        raise ContractError("notice_version must be a positive integer or unknown")
    source_hash = raw.get("source_record_sha256", raw.get("source_hash"))
    if source_hash is not None and (
        not isinstance(source_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", source_hash)
    ):
        raise ContractError("source_record_sha256 must be a SHA-256 hex digest")
    record = {
        "id": notice_id,
        "title": _text(raw.get("title"), "title"),
        "buyer": _text(raw.get("buyer"), "buyer", optional=True),
        "countries": _strings(raw.get("countries", []), "countries"),
        "cpv_codes": _strings(raw.get("cpv_codes", []), "cpv_codes"),
        "publication_date": _day(raw.get("publication_date"), "publication_date"),
        "deadline": _day(raw.get("deadline"), "deadline", optional=True),
        "deadline_dates": sorted(
            {
                _day(value, "deadline_dates")
                for value in _strings(
                    raw.get("deadline_dates", [raw["deadline"]] if raw.get("deadline") else []),
                    "deadline_dates",
                )
            }
        ),
        "deadline_label": _text(
            raw.get("deadline_label", "Earliest reported lot deadline"), "deadline_label"
        ),
        "type": _text(raw.get("notice_type"), "notice_type", optional=True),
        "source_url": url,
        "correction_refs": _strings(correction_refs, "correction_refs"),
        "notice_identifier": _text(
            raw.get("notice_identifier", source_refs.get("notice_identifier")),
            "notice_identifier",
            optional=True,
        ),
        "notice_version": version,
        "source_record_sha256": source_hash,
    }
    for cpv in record["cpv_codes"]:
        if not re.fullmatch(r"\d{8}(?:-\d)?", cpv):
            raise ContractError(f"Invalid CPV code for {notice_id}: {cpv}")
    for country in record["countries"]:
        if not re.fullmatch(r"[A-Z]{2,3}", country):
            raise ContractError(f"Invalid country code for {notice_id}: {country}")
    earliest = min(record["deadline_dates"]) if record["deadline_dates"] else None
    if record["deadline"] != earliest:
        raise ContractError("Earliest deadline does not reconcile to the reported date set")
    if notice_id in record["correction_refs"]:
        raise ContractError(f"Self-referential correction: {notice_id}")
    scope = raw.get("scope", "primary")
    if scope not in {"primary", "context"}:
        raise ContractError("Record scope must be primary or context")
    record["content_sha256"] = digest({"id": record["id"], **{key: record[key] for key in FIELDS}})
    record["scope"] = scope
    return record


def _resolve_parents(records: dict[str, dict]) -> None:
    """Resolve stable source pointers against observed identities, never guessed text."""
    aliases: dict[str, set[str]] = {}
    for item in records.values():
        keys = [item["id"]]
        if item["notice_identifier"] and item["notice_version"]:
            keys += [
                f"{item['notice_identifier']}-{item['notice_version']:02d}",
                f"{item['notice_identifier']}-{item['notice_version']}",
            ]
        for key in keys:
            aliases.setdefault(key, set()).add(item["id"])
    for item in records.values():
        parents = set()
        resolutions = []
        for ref in item["correction_refs"]:
            candidates = sorted(aliases.get(ref, set()))
            parents.update(candidates or [ref])
            resolutions.append(
                {
                    "reference": ref,
                    "status": "resolved"
                    if len(candidates) == 1
                    else "ambiguous"
                    if candidates
                    else "missing",
                    "notice_ids": candidates,
                }
            )
        if item["id"] in parents:
            raise ContractError(f"Self-referential correction: {item['id']}")
        item["previous_notice_ids"] = sorted(parents)
        item["reference_resolution"] = resolutions


def _acyclic(records: dict[str, dict]) -> None:
    """Iterative DFS avoids recursion depth dependence on source history length."""
    done: set[str] = set()
    visiting: set[str] = set()
    for start in records:
        if start in done:
            continue
        stack = [(start, False)]
        while stack:
            current, finished = stack.pop()
            if finished:
                visiting.discard(current)
                done.add(current)
                continue
            if current in done:
                continue
            if current in visiting:
                raise ContractError(f"Cyclic correction references include {current}")
            visiting.add(current)
            stack.append((current, True))
            for parent in records[current]["previous_notice_ids"]:
                if parent in records:
                    stack.append((parent, False))


def _comparison(record: dict, records: dict[str, dict]) -> dict:
    parents = record["previous_notice_ids"]
    missing = [parent for parent in parents if parent not in records]
    result = {"status": "root", "parent_id": None, "changes": [], "missing_parent_ids": missing}
    if len(parents) > 1:
        result["status"] = "ambiguous_parent"
    elif missing:
        result["status"] = "missing_parent"
    elif parents:
        parent = records[parents[0]]
        if parent["publication_date"] > record["publication_date"]:
            raise ContractError(f"Correction {record['id']} predates its referenced parent")
        result["status"] = "compared"
        result["parent_id"] = parent["id"]
        result["parent_url"] = parent["source_url"]
        result["changes"] = [
            {"field": key, "label": label, "before": parent[key], "after": record[key]}
            for key, label in COMPARE_FIELDS.items()
            if parent[key] != record[key]
        ]
    return result


def _fit(record: dict) -> dict:
    tests = [
        (
            "service",
            any(c.startswith("72") for c in record["cpv_codes"]),
            "IT services CPV category (72)",
            "No IT-services CPV category reported",
        ),
        (
            "country",
            bool(set(record["countries"]) & TARGET_COUNTRIES),
            "Buyer based in PT, DE, NL, GB or CH",
            "No configured buyer country reported",
        ),
        (
            "title",
            bool(DATA_TERMS.search(record["title"])),
            "Title contains a configured data/analytics term",
            "No configured data/analytics title term",
        ),
    ]
    criteria = [
        {"key": key, "matched": matched, "reason": yes if matched else no}
        for key, matched, yes, no in tests
    ]
    score = sum(x["matched"] for x in criteria)
    return {
        "label": "Strong rule match"
        if score == 3
        else "Partial rule match"
        if score
        else "No configured match",
        "score": score,
        "reasons": [x["reason"] for x in criteria if x["matched"]],
        "criteria": criteria,
    }


def validate_release(release: object) -> dict:
    if not isinstance(release, dict) or release.get("schema_version") != 1:
        raise ContractError("Unsupported release schema")
    meta = release.get("release")
    if not isinstance(meta, dict) or not isinstance(release.get("notices"), list):
        raise ContractError("Release metadata or notices are missing")
    source = release.get("source")
    if not isinstance(source, dict) or source.get("name") != "TED":
        raise ContractError("Release source must be TED")
    captured_at = _capture_time(source.get("captured_at"))
    capture_instant = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    generated_at = _capture_time(meta.get("generated_from_capture_at"))
    if datetime.fromisoformat(generated_at.replace("Z", "+00:00")) != capture_instant:
        raise ContractError("Release capture time does not reconcile to source metadata")
    if len(release["notices"]) > MAX_RECORDS:
        raise ContractError("Retained history exceeds the configured demonstration bound")
    candidate = {k: v for k, v in release.items() if k != "release"}
    expected = digest(
        {
            "payload": candidate,
            "source_sha256": meta.get("source_sha256"),
            "code_sha256": meta.get("code_sha256"),
        }
    )
    if meta.get("id") != expected or meta.get("payload_sha256") != digest(candidate):
        raise ContractError("Release fingerprint does not match its content")
    seen = set()
    for item in release["notices"]:
        if not isinstance(item, dict) or item.get("id") in seen:
            raise ContractError("Duplicate or invalid notice in release")
        seen.add(item.get("id"))
        raw = {
            "notice_id": item.get("id"),
            "notice_type": item.get("type"),
            **{key: item.get(key) for key in FIELDS if key != "type"},
        }
        normalized = normalize_record(raw)
        if normalized["content_sha256"] != item.get("content_sha256"):
            raise ContractError("Notice content fingerprint does not match")
        if item.get("scope") not in {"primary", "context", "retained"}:
            raise ContractError("Release notice scope must be primary, context or retained")
        first_seen = datetime.fromisoformat(
            _capture_time(item.get("first_seen_at")).replace("Z", "+00:00")
        )
        last_seen = datetime.fromisoformat(
            _capture_time(item.get("last_seen_at")).replace("Z", "+00:00")
        )
        if not first_seen <= last_seen <= capture_instant:
            raise ContractError("Notice observation times must satisfy first <= last <= capture")
        if item["scope"] in {"primary", "context"} and last_seen != capture_instant:
            raise ContractError("Current-capture notices must be last seen at the capture time")
    if release.get("summary", {}).get("notice_count") != len(seen):
        raise ContractError("Release count does not reconcile")
    return release


def compile_release(snapshot: object, previous: dict | None = None) -> dict:
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
        raise ContractError("Unsupported source schema")
    captured_at = _capture_time(snapshot.get("captured_at"))
    source = snapshot.get("source")
    if not isinstance(source, dict) or source.get("name") != "TED":
        raise ContractError("Source must be TED")
    coverage = source.get("coverage")
    if not isinstance(coverage, dict) or coverage.get("complete_for_selection") is not True:
        raise ContractError("Incomplete source selection; previous release must remain available")
    selected_count = coverage.get("selected_count")
    if type(selected_count) is not int or selected_count < 0:
        raise ContractError("selected_count must be a nonnegative integer")
    total = coverage.get("total_matching")
    if type(total) is not int or total != selected_count:
        raise ContractError("Selected primary count must equal the reported query population")
    scope = _text(source.get("scope"), "source.scope")
    query = _text(source.get("query"), "source.query")
    _text(coverage.get("description"), "coverage.description")
    raw_records = snapshot.get("records")
    if not isinstance(raw_records, list) or len(raw_records) > MAX_RECORDS:
        raise ContractError(f"records must be an array with at most {MAX_RECORDS} entries")
    incoming: dict[str, dict] = {}
    duplicates = 0
    for raw in raw_records:
        item = normalize_record(raw)
        existing = incoming.get(item["id"])
        if existing:
            if existing["content_sha256"] != item["content_sha256"]:
                raise ContractError(f"Conflicting content for immutable notice {item['id']}")
            duplicates += 1
            if item["scope"] == "primary":
                existing["scope"] = "primary"
        else:
            incoming[item["id"]] = item
    if sum(item["scope"] == "primary" for item in incoming.values()) != selected_count:
        raise ContractError("Selected primary notice count does not reconcile")

    records: dict[str, dict] = {}
    if previous is not None:
        validate_release(previous)
        old_time = _capture_time(previous["source"]["captured_at"])
        if datetime.fromisoformat(captured_at.replace("Z", "+00:00")) < datetime.fromisoformat(
            old_time.replace("Z", "+00:00")
        ):
            raise ContractError("An older capture cannot overwrite a newer release")
        for item in previous["notices"]:
            records[item["id"]] = {
                key: item[key]
                for key in ("id", *FIELDS, "content_sha256", "first_seen_at", "last_seen_at")
            }
            records[item["id"]]["scope"] = "retained"
    for notice_id, item in incoming.items():
        existing = records.get(notice_id)
        if existing and existing["content_sha256"] != item["content_sha256"]:
            raise ContractError(
                f"Published identity {notice_id} changed; review instead of silently rewriting it"
            )
        item["first_seen_at"] = existing["first_seen_at"] if existing else captured_at
        item["last_seen_at"] = captured_at
        records[notice_id] = item
    if len(records) > MAX_RECORDS:
        raise ContractError("Retained history exceeds the configured demonstration bound")
    _resolve_parents(records)
    _acyclic(records)
    parents = {
        parent
        for item in records.values()
        for parent in item["previous_notice_ids"]
        if parent in records
    }
    for item in records.values():
        item["comparison"] = _comparison(item, records)
        item["fit"] = _fit(item)
        item["has_known_successor"] = item["id"] in parents
    notices = sorted(
        records.values(), key=lambda item: (item["publication_date"], item["id"]), reverse=True
    )
    statuses = Counter(item["comparison"]["status"] for item in notices)
    output_source = {
        "name": "TED",
        "captured_at": captured_at,
        "scope": scope,
        "query": query,
        "coverage": coverage,
    }
    payload = {
        "schema_version": 1,
        "source": output_source,
        "summary": {
            "notice_count": len(notices),
            "primary_count": selected_count,
            "context_count": sum(x["scope"] == "context" for x in notices),
            "retained_count": sum(x["scope"] == "retained" for x in notices),
            "root_count": statuses["root"],
            "linked_count": statuses["compared"],
            "unresolved_count": statuses["missing_parent"] + statuses["ambiguous_parent"],
            "changed_count": sum(bool(x["comparison"]["changes"]) for x in notices),
            "country_count": len({c for x in notices for c in x["countries"]}),
            "duplicate_deliveries": duplicates,
        },
        "notices": notices,
        "methodology": {
            "grain": (
                "One TED publication identifier; source-linked corrections are separate "
                "immutable publications."
            ),
            "fit": (
                "Three transparent rules for an illustrative data/software supplier; "
                "not eligibility, award probability or an evaluated prediction."
            ),
            "comparison": (
                "Only explicit correction references are compared. A root means no correction "
                "pointer was supplied; it does not prove the original publication of a procedure."
            ),
            "deadline": (
                "Earliest reported lot deadline is a calendar date. Other lots may differ. "
                "The full date set is compared without inferring lot associations. "
                "Missing dates remain unknown; consult the source for current requirements."
            ),
            "countries": "Buyer country, not place of performance or remote-work eligibility.",
            "limitations": [
                "Bounded public-source capture, not complete market coverage "
                "or a live procurement service.",
                "An absent notice in a later selection is retained; absence is not "
                "interpreted as withdrawal.",
                "A known successor is a linked correction, not proof that a contract "
                "is cancelled or closed.",
                "No fuzzy entity links or inferred correction parents are created.",
                "The rule match has no independent relevance labels or measured business outcomes.",
                "Atomic replacement protects one local JSON file; it does not establish "
                "distributed transactions or power-loss durability.",
            ],
        },
    }
    normalized_snapshot = {
        **snapshot,
        "records": sorted(raw_records, key=lambda x: (x.get("notice_id", ""), canonical(x))),
    }
    source_hash = digest(normalized_snapshot)
    code_hash = code_fingerprint()
    payload_hash = digest(payload)
    payload["release"] = {
        "id": digest({"payload": payload, "source_sha256": source_hash, "code_sha256": code_hash}),
        "payload_sha256": payload_hash,
        "source_sha256": source_hash,
        "code_sha256": code_hash,
        "generated_from_capture_at": captured_at,
    }
    return validate_release(payload)
