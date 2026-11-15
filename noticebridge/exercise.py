"""Record an actual bounded process-kill exercise over explicitly synthetic notices."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .engine import ContractError, canonical, code_fingerprint, digest
from .publish import build_to_path, verify_path


def _record(number: str, **changes) -> dict:
    return {
        "notice_id": number,
        "title": "Synthetic data platform procurement",
        "buyer": "Synthetic municipality",
        "countries": ["DEU"],
        "cpv_codes": ["72000000"],
        "publication_date": "2026-11-12",
        "deadline": "2026-12-01",
        "notice_type": "cn-standard",
        "previous_notice_ids": [],
        "source_url": f"https://ted.europa.eu/en/notice/-/detail/{number}",
        **changes,
    }


def _snapshot(*records, complete=True) -> dict:
    return {
        "schema_version": 1,
        "captured_at": "2026-11-15T00:00:00Z",
        "source": {
            "name": "TED",
            "scope": "Synthetic recovery fixture; these are not captured public notices",
            "query": "synthetic recovery fixture",
            "coverage": {
                "bounded": True,
                "selected_count": len(records),
                "total_matching": len(records),
                "complete_for_selection": complete,
                "description": "Synthetic records for a controlled failure exercise",
            },
        },
        "records": list(records),
    }


def run_exercise(output: Path) -> dict:
    if output.exists():
        raise ContractError("Evidence output already exists; use a new dated filename")
    started = time.perf_counter()
    checks = []

    def check(name, observed):
        checks.append({"name": name, "passed": bool(observed)})
        if not observed:
            raise ContractError(f"Exercise failed: {name}")

    with tempfile.TemporaryDirectory(prefix="noticebridge-exercise-") as directory:
        folder = Path(directory)
        source, published, ready = folder / "source.json", folder / "data.json", folder / "ready"
        original = _record("100-2026")
        correction = _record(
            "101-2026",
            previous_notice_ids=["100-2026"],
            publication_date="2026-11-13",
            deadline="2026-12-15",
        )
        initial = _snapshot(original)
        changed = _snapshot(original, correction)
        source.write_bytes(canonical(initial))
        build_to_path(source, published)
        old_bytes = published.read_bytes()
        old_hash = hashlib.sha256(old_bytes).hexdigest()
        check("initial_one_notice_release", json.loads(old_bytes)["summary"]["notice_count"] == 1)

        source.write_bytes(canonical(_snapshot(original, correction, complete=False)))
        try:
            build_to_path(source, published)
            refused = False
        except ContractError:
            refused = True
        check("incomplete_source_refused", refused)
        check(
            "incomplete_source_preserved_exact_previous_bytes", published.read_bytes() == old_bytes
        )

        source.write_bytes(canonical(changed))
        worker = """
import os, sys, time
from pathlib import Path
from noticebridge.publish import build_to_path
def staged_boundary(staged):
    marker = Path(sys.argv[3])
    temporary = marker.with_suffix('.tmp')
    temporary.write_text(str(staged), encoding='utf-8')
    os.replace(temporary, marker)
    while True:
        time.sleep(1)
build_to_path(Path(sys.argv[1]), Path(sys.argv[2]), before_replace=staged_boundary)
"""
        process = subprocess.Popen(
            [sys.executable, "-c", worker, str(source), str(published), str(ready)],
            cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 15
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            check("observed_staged_write_barrier", ready.exists())
            staged = Path(ready.read_text(encoding="utf-8"))
            staged_bytes = staged.read_bytes()
            check(
                "staged_candidate_contains_two_notices",
                json.loads(staged_bytes)["summary"]["notice_count"] == 2,
            )
            try:
                build_to_path(source, published)
                excluded = False
            except ContractError as exc:
                excluded = "Another publisher" in str(exc)
            check("competing_publisher_denied_while_lock_held", excluded)
            process.kill()
            process.wait(timeout=5)
            check("worker_abruptly_terminated", process.returncode != 0)
            check(
                "worker_death_preserved_exact_previous_bytes", published.read_bytes() == old_bytes
            )
            check(
                "orphan_stage_is_separate_from_public_payload",
                staged.exists() and staged != published,
            )
            recovered = build_to_path(source, published)
            check(
                "retry_published_after_process_owned_lock_released",
                recovered["status"] == "published",
            )
            new_bytes = published.read_bytes()
            released = json.loads(new_bytes)
            actual = next(n for n in released["notices"] if n["id"] == "101-2026")
            expected_deadline = {
                "field": "deadline",
                "label": "Earliest reported lot deadline",
                "before": "2026-12-01",
                "after": "2026-12-15",
            }
            check(
                "observed_correction_matches_hand_written_deadline_oracle",
                expected_deadline in actual["comparison"]["changes"],
            )
            check(
                "published_release_reproduces",
                verify_path(source, published)["status"] == "verified",
            )
            check(
                "exact_replay_reports_unchanged",
                build_to_path(source, published)["status"] == "unchanged",
            )
            check("exact_replay_preserves_all_bytes", published.read_bytes() == new_bytes)
            source.write_bytes(
                canonical(_snapshot(_record("100-2026", title="Conflicting identity")))
            )
            try:
                build_to_path(source, published)
                refused = False
            except ContractError:
                refused = True
            check("immutable_identity_rewrite_refused", refused)
            check(
                "identity_conflict_preserves_recovered_release", published.read_bytes() == new_bytes
            )
            report = {
                "schema_version": 1,
                "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "scope": (
                    "Actual local subprocess termination over two synthetic notices; not a TED "
                    "outage, uptime measurement or cloud recovery benchmark."
                ),
                "source_fixture_sha256": digest(changed),
                "code_sha256": code_fingerprint(),
                "runtime": {"python": platform.python_version(), "platform": platform.platform()},
                "observed_boundary": (
                    "Candidate bytes were flushed, fsynced and validated; child signaled a file "
                    "barrier before os.replace, then parent killed it."
                ),
                "worker_exit_code": process.returncode,
                "previous_payload_sha256": old_hash,
                "candidate_payload_sha256": hashlib.sha256(staged_bytes).hexdigest(),
                "recovered_payload_sha256": hashlib.sha256(new_bytes).hexdigest(),
                "previous_notice_count": 1,
                "recovered_notice_count": 2,
                "wall_seconds": round(time.perf_counter() - started, 6),
                "checks": checks,
                "passed": len(checks),
                "failed": 0,
                "limits": [
                    "One local writer and one JSON publication boundary; no distributed sinks.",
                    "This tests abrupt process exit before replacement, not host power loss.",
                    "An orphan stage can remain after a kill; it is never served as data.json.",
                    "OS advisory locks only coordinate publishers using this implementation.",
                ],
            }
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as handle:
        handle.write(canonical(report))
    return {"status": "passed", "checks": len(checks), "output": str(output)}
