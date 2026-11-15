"""Archive real captures, replay from empty state, and promote one verified pointer.

Publication dates partition the source. Observation timestamps order the archive.
Content-addressed assets are immutable; only current.json is replaced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .engine import ContractError, canonical, code_fingerprint, compile_release, digest
from .publish import MAX_JSON_BYTES, parse_json, read_bytes_bounded, read_json, writer_lock

MAX_CAPTURES = 100
HASH = re.compile(r"^[a-f0-9]{64}$")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def utc(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() != timedelta(0):
            raise ValueError("UTC required")
        return result
    except (ValueError, TypeError, AttributeError) as exc:
        raise ContractError("Observation time must be explicit UTC") from exc


def atomic_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".stage-", delete=False) as f:
            staged = Path(f.name)
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(staged, path)
    finally:
        if staged:
            staged.unlink(missing_ok=True)


def immutable_bytes(path: Path, raw: bytes) -> None:
    """A corrupt existing address is an incident, never an overwrite opportunity."""
    if len(raw) > MAX_JSON_BYTES:
        raise ContractError("Immutable asset exceeds the 64 MiB demonstration bound")
    if path.exists():
        if read_bytes_bounded(path) != raw:
            raise ContractError(f"Immutable artifact conflict: {path.name}")
    else:
        atomic_bytes(path, raw)


def read_archive(data: Path) -> tuple[dict, list[dict]]:
    index = read_json(data / "captures.json")
    entries = index.get("captures")
    if index.get("schema_version") != 1 or not isinstance(entries, list):
        raise ContractError("Unsupported capture index")
    if not 1 <= len(entries) <= MAX_CAPTURES:
        raise ContractError(f"Archive requires 1–{MAX_CAPTURES} captures")
    snapshots = []
    seen = set()
    prior = None
    for entry in entries:
        fingerprint = entry.get("sha256", "")
        if not isinstance(fingerprint, str) or not HASH.fullmatch(fingerprint):
            raise ContractError("Invalid capture fingerprint")
        if entry.get("path") != f"captures/{fingerprint}.json" or fingerprint in seen:
            raise ContractError("Duplicate capture or invalid archive path")
        if entry.get("mode") not in {"bootstrap", "backfill", "refresh"}:
            raise ContractError("Capture mode must describe actual collection intent")
        day = entry.get("publication_day")
        try:
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError("Noncanonical day")
        except (TypeError, ValueError) as exc:
            raise ContractError("Invalid publication partition") from exc
        path = data / entry["path"]
        raw = read_bytes_bounded(path)
        if sha(raw) != fingerprint:
            raise ContractError(f"Archived source hash mismatch: {path.name}")
        source = parse_json(raw, path.name)
        observed = utc(source.get("captured_at"))
        if entry.get("captured_at") != source.get("captured_at"):
            raise ContractError("Index observation time differs from archived source")
        if prior is not None and observed < prior:
            raise ContractError("Capture observation times regress")
        if any(
            r.get("scope", "primary") == "primary" and r.get("publication_date") != day
            for r in source.get("records", [])
        ):
            raise ContractError("Primary row does not match publication partition")
        seen.add(fingerprint)
        snapshots.append(source)
        prior = observed
    return index, snapshots


def import_capture(data: Path, source: Path, day: str, mode: str) -> dict:
    return import_batch(data, [(source, day, mode)])[0]


def import_batch(data: Path, captures: list[tuple[Path, str, str]]) -> list[dict]:
    """Either the entire ordered batch validates against history, or index stays unchanged."""
    data.mkdir(parents=True, exist_ok=True)
    index_path = data / "captures.json"
    with writer_lock(index_path):
        if index_path.exists():
            index, _ = read_archive(data)
        else:
            index = {"schema_version": 1, "captures": []}
        candidate = {"schema_version": 1, "captures": list(index["captures"])}
        additions = {}
        results = []
        for source, day, mode in captures:
            raw = read_bytes_bounded(source)
            snapshot = parse_json(raw, source.name)
            compile_release(snapshot)
            fingerprint = sha(raw)
            matched = next((e for e in candidate["captures"] if e["sha256"] == fingerprint), None)
            if matched:
                if matched["publication_day"] != day or matched["mode"] != mode:
                    raise ContractError("Repeated capture has conflicting index metadata")
                results.append({"status": "unchanged", "sha256": fingerprint})
                continue
            entry = {
                "path": f"captures/{fingerprint}.json",
                "sha256": fingerprint,
                "captured_at": snapshot["captured_at"],
                "publication_day": day,
                "mode": mode,
            }
            candidate["captures"].append(entry)
            additions[entry["path"]] = raw
            results.append({"status": "archived", "sha256": fingerprint})
        if not additions:
            return results
        # Validate the candidate index in an isolated directory before replacing it.
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            for old in index["captures"]:
                target = temp / old["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(read_bytes_bounded(data / old["path"]))
            for name, raw in additions.items():
                (temp / name).parent.mkdir(parents=True, exist_ok=True)
                (temp / name).write_bytes(raw)
            (temp / "captures.json").write_bytes(canonical(candidate))
            replay(temp)
        for name, raw in additions.items():
            immutable_bytes(data / name, raw)
        atomic_bytes(index_path, canonical(candidate))
    return results


def acquisition(snapshot: dict) -> dict:
    evidence = snapshot.get("evidence", {})
    requests = [*evidence.get("search_requests", []), *evidence.get("api_xml_checks", [])]
    attempts = [attempt for request in requests for attempt in request.get("attempts", [])]
    checks = [
        check
        for item in evidence.get("api_xml_checks", [])
        for check in item.get("checks", {}).values()
    ]
    return {
        "requests": len(requests),
        "attempts": len(attempts),
        "rate_limits": sum(a.get("status") == 429 for a in attempts),
        "retries": sum(max(len(r.get("attempts", [])) - 1, 0) for r in requests),
        "xml_checks_passed": sum(c is True for c in checks),
        "xml_checks_total": len(checks),
    }


def replay(data: Path) -> tuple[dict, list[dict], list[dict]]:
    """No consumer output is used as input; historical truth comes from captures."""
    index, snapshots = read_archive(data)
    releases = []
    runs = []
    previous = None
    for sequence, (entry, snapshot) in enumerate(zip(index["captures"], snapshots), 1):
        started = time.perf_counter()
        release = compile_release(snapshot, previous)
        elapsed = round((time.perf_counter() - started) * 1000, 3)
        prior = {r["id"]: r for r in previous["notices"]} if previous else {}
        incoming = {r["notice_id"] for r in snapshot["records"]}
        resolved = sum(
            r["id"] in prior
            and prior[r["id"]]["comparison"]["status"] in {"missing_parent", "ambiguous_parent"}
            and r["comparison"]["status"] == "compared"
            for r in release["notices"]
        )
        raw = canonical(release)
        fingerprint = sha(raw)
        runs.append(
            {
                **{k: entry[k] for k in ("mode", "publication_day", "captured_at")},
                "sequence": sequence,
                "source_sha256": entry["sha256"],
                "source_path": entry["path"],
                "release_id": release["release"]["id"],
                "release_path": f"releases/{fingerprint}.json",
                "release_sha256": fingerprint,
                "counts": {
                    "incoming": len(incoming),
                    "new": len(incoming - prior.keys()),
                    "already_seen": len(incoming & prior.keys()),
                    "retained": len(prior.keys() - incoming),
                    "resolved_parents": resolved,
                    "total": len(release["notices"]),
                },
                "duration_ms": elapsed,
                "acquisition": acquisition(snapshot),
            }
        )
        releases.append(release)
        previous = release
    return index, releases, runs


def asset(web: Path, descriptor: dict) -> bytes:
    fingerprint = descriptor.get("sha256", "")
    if not isinstance(fingerprint, str) or not HASH.fullmatch(fingerprint):
        raise ContractError("Invalid asset fingerprint")
    if descriptor.get("path") != f"releases/{fingerprint}.json":
        raise ContractError("Invalid immutable asset path")
    raw = read_bytes_bounded(web / descriptor["path"])
    if sha(raw) != fingerprint:
        raise ContractError("Published asset bytes do not match the pointer")
    return raw


def verify_edition(data: Path, web: Path, pointer: dict | None = None) -> dict:
    pointer = pointer if pointer is not None else read_json(web / "current.json")
    if pointer.get("schema_version") != 1:
        raise ContractError("Unsupported release pointer")
    index, releases, runs = replay(data)
    operations = parse_json(asset(web, pointer["operations"]), "operations")
    if operations.get("schema_version") != 1 or utc(operations.get("built_at")) < utc(
        runs[-1]["captured_at"]
    ):
        raise ContractError("Invalid operations schema or build observation time")
    if asset(web, pointer["release"]) != canonical(releases[-1]):
        raise ContractError("Current release differs from independent archived-source replay")
    capacity = operations.get("archive_capacity")
    if (
        not isinstance(capacity, dict)
        or any(type(capacity.get(k)) is not int for k in ("maximum", "remaining"))
        or capacity != {"maximum": MAX_CAPTURES, "remaining": MAX_CAPTURES - len(runs)}
    ):
        raise ContractError("Archive capacity differs from verified capture count")
    if (
        operations.get("archive_sha256") != digest(index)
        or operations.get("code_sha256") != code_fingerprint()
        or operations.get("capture_count") != len(runs)
        or operations.get("replay_verified") is not True
        or operations.get("current_release_id") != releases[-1]["release"]["id"]
        or operations.get("publication_days") != sorted({r["publication_day"] for r in runs})
        or operations.get("first_capture_at") != runs[0]["captured_at"]
        or operations.get("last_capture_at") != runs[-1]["captured_at"]
        or operations.get("acquisition")
        != {key: sum(r["acquisition"][key] for r in runs) for key in runs[0]["acquisition"]}
    ):
        raise ContractError("Operations summary does not reconcile to archived evidence")
    actual_runs = operations.get("runs")
    if not isinstance(actual_runs, list) or len(actual_runs) != len(runs):
        raise ContractError("Run ledger does not reconcile")
    for expected, actual, release in zip(runs, actual_runs, releases):
        if {k: v for k, v in expected.items() if k != "duration_ms"} != {
            k: v for k, v in actual.items() if k != "duration_ms"
        }:
            raise ContractError("Run ledger differs from independent replay")
        duration = actual.get("duration_ms")
        if type(duration) not in {int, float} or not 0 <= duration <= 600_000:
            raise ContractError("Invalid measured replay duration")
        descriptor = {"path": actual["release_path"], "sha256": actual["release_sha256"]}
        if asset(web, descriptor) != canonical(release):
            raise ContractError("Historical release differs from archived-source replay")
    return {
        "status": "verified",
        "captures": len(runs),
        "notices": len(releases[-1]["notices"]),
        "release_id": releases[-1]["release"]["id"],
        "replay_from_empty": True,
    }


def publish_edition(data: Path, web: Path, *, before_promote=None) -> dict:
    web.mkdir(parents=True, exist_ok=True)
    with writer_lock(data / "captures.json"), writer_lock(web / "current.json"):
        index, releases, runs = replay(data)
        existing = web / "current.json"
        if existing.exists():
            old = read_json(existing)
            operations = parse_json(asset(web, old["operations"]), "operations")
            if (
                operations.get("archive_sha256") == digest(index)
                and operations.get("code_sha256") == code_fingerprint()
            ):
                return {**verify_edition(data, web), "status": "unchanged"}
        for release, run in zip(releases, runs):
            immutable_bytes(web / run["release_path"], canonical(release))
        operations = {
            "schema_version": 1,
            "built_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "archive_sha256": digest(index),
            "code_sha256": code_fingerprint(),
            "capture_count": len(runs),
            "archive_capacity": {"maximum": MAX_CAPTURES, "remaining": MAX_CAPTURES - len(runs)},
            "publication_days": sorted({r["publication_day"] for r in runs}),
            "first_capture_at": runs[0]["captured_at"],
            "last_capture_at": runs[-1]["captured_at"],
            "replay_verified": True,
            "current_release_id": releases[-1]["release"]["id"],
            "runs": runs,
            "acquisition": {
                key: sum(r["acquisition"][key] for r in runs) for key in runs[0]["acquisition"]
            },
            "limitations": [
                "Publication dates describe historical source partitions, not days of operation.",
                "Observation timestamps are actual capture times; backfill is labelled explicitly.",
                "Run durations measure replay compilation, not network acquisition or uptime.",
                "Retained history is reconstructed from immutable captures from empty state.",
                "A code change creates new releases; old immutable files remain available.",
                "One atomic local pointer selects release and ledger; no distributed SLA claimed.",
                "GitHub scheduling can be delayed; visible source freshness is not guaranteed.",
            ],
        }
        operations_raw = canonical(operations)
        operations_sha = sha(operations_raw)
        operations_path = f"releases/{operations_sha}.json"
        immutable_bytes(web / operations_path, operations_raw)
        pointer = {
            "schema_version": 1,
            "release": {
                "path": runs[-1]["release_path"],
                "sha256": runs[-1]["release_sha256"],
            },
            "operations": {"path": operations_path, "sha256": operations_sha},
        }
        result = verify_edition(data, web, pointer)
        if before_promote:
            before_promote(pointer)
        atomic_bytes(web / "current.json", canonical(pointer))
        return {**result, "status": "published"}


def refresh(data: Path, web: Path, *, lookback: int = 3) -> dict:
    from sources.collect import atomic_write, collect_day

    if not 1 <= lookback <= 7:
        raise ContractError("Refresh lookback must be 1–7 calendar days")
    today = datetime.now(timezone.utc).date()
    # Collect the whole batch first. A failed request does not mutate the index.
    with tempfile.TemporaryDirectory() as directory:
        staged = []
        for offset in range(lookback, 0, -1):
            day = today - timedelta(days=offset)
            path = Path(directory) / f"{day}.json"
            atomic_write(path, collect_day(day))
            staged.append((day.isoformat(), path))
        import_batch(data, [(path, day, "refresh") for day, path in staged])
    return publish_edition(data, web)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("import", "publish", "verify", "refresh"))
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--web", type=Path, default=Path("web"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--day")
    parser.add_argument("--mode", choices=("bootstrap", "backfill", "refresh"), default="backfill")
    parser.add_argument("--lookback", type=int, default=3)
    args = parser.parse_args()
    if args.command == "import":
        if not args.source or not args.day:
            parser.error("import requires --source and --day")
        result = import_capture(args.data, args.source, args.day, args.mode)
    elif args.command == "verify":
        result = verify_edition(args.data, args.web)
    elif args.command == "refresh":
        result = refresh(args.data, args.web, lookback=args.lookback)
    else:
        result = publish_edition(args.data, args.web)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
