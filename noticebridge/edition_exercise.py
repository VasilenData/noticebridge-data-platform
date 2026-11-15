"""Observe local edition recovery across a process kill and archived-source corruption.

Every source record here is synthetic. The subprocess is stopped only after an
atomic marker proves the complete candidate bundle reached its verified boundary.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .engine import ContractError, canonical, code_fingerprint, digest
from .exercise import _record, _snapshot
from .operations import asset, import_capture, publish_edition, sha, verify_edition
from .publish import read_json

WORKER = """
import sys, time
from pathlib import Path
from noticebridge.engine import canonical
from noticebridge.operations import atomic_bytes, publish_edition

def verified_boundary(pointer):
    atomic_bytes(Path(sys.argv[3]), canonical(pointer))
    while True:
        time.sleep(1)

publish_edition(Path(sys.argv[1]), Path(sys.argv[2]), before_promote=verified_boundary)
"""


def _publish_after_exit(data: Path, web: Path, process, *, timeout_seconds: float = 5) -> tuple:
    """Probe actual lock availability after exit; do not assume exit means immediate unlock."""
    if process.poll() is None:
        raise ContractError("Recovery cannot begin before observed worker termination")
    started = time.perf_counter()
    deadline = time.monotonic() + timeout_seconds
    probes = []
    while True:
        attempt_started = round(time.perf_counter() - started, 6)
        try:
            result = publish_edition(data, web)
        except ContractError as exc:
            # Do not turn corruption, validation failures or unrelated OS errors
            # into a successful recovery by retrying them indiscriminately.
            if str(exc) != "Another publisher holds this output lock":
                raise
            probes.append(
                {
                    "status": "lock_still_held",
                    "attempt_started_seconds": attempt_started,
                    "elapsed_seconds": round(time.perf_counter() - started, 6),
                    "cause": type(exc.__cause__).__name__ if exc.__cause__ else None,
                }
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ContractError(
                    "Worker exited but publisher locks did not release in time"
                ) from exc
            # This bounded poll is conditional on an observed lock denial, not
            # a guessed delay before the first recovery attempt.
            time.sleep(min(0.02, remaining))
        else:
            probes.append(
                {
                    "status": "published_after_lock_acquisition",
                    "attempt_started_seconds": attempt_started,
                    "elapsed_seconds": round(time.perf_counter() - started, 6),
                }
            )
            return result, {
                "method": "Conditional publication retries after confirmed child exit",
                "timeout_seconds": timeout_seconds,
                "probe_interval_seconds": 0.02,
                "probes": probes,
                "lock_denials_after_exit": len(probes) - 1,
                "publication_completed_after_seconds": round(time.perf_counter() - started, 6),
                "timing_scope": (
                    "Probe times bound observed contention. Completion also includes replay "
                    "and publication work; it is not an exact kernel unlock timestamp."
                ),
            }


def run_exercise(output: Path) -> dict:
    if output.exists():
        raise ContractError("Evidence output already exists; use a new dated filename")
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    checks = []

    def check(name: str, observed: bool) -> None:
        checks.append(
            {
                "name": name,
                "passed": bool(observed),
                "elapsed_seconds": round(time.perf_counter() - started, 6),
            }
        )
        if not observed:
            raise ContractError(f"Edition exercise failed: {name}")

    with tempfile.TemporaryDirectory(prefix="noticebridge-edition-exercise-") as directory:
        root = Path(directory)
        data, web, ready = root / "archive", root / "web", root / "verified-candidate.json"
        initial = _snapshot(_record("100-2026"))
        correction = _snapshot(
            _record(
                "101-2026",
                publication_date="2026-11-13",
                deadline="2026-12-15",
                previous_notice_ids=["100-2026"],
            )
        )
        correction["captured_at"] = "2026-11-15T00:05:00Z"
        first_source, second_source = root / "first.json", root / "second.json"
        first_source.write_bytes(canonical(initial))
        second_source.write_bytes(canonical(correction))
        import_capture(data, first_source, "2026-11-12", "bootstrap")
        publish_edition(data, web)
        first_verified = verify_edition(data, web)
        check(
            "initial_edition_replays_one_capture_and_one_notice",
            first_verified["captures"] == 1
            and first_verified["notices"] == 1
            and first_verified["replay_from_empty"],
        )
        pointer_path = web / "current.json"
        old_pointer_bytes = pointer_path.read_bytes()
        old_pointer = json.loads(old_pointer_bytes)
        old_release_bytes = asset(web, old_pointer["release"])
        old_operations_bytes = asset(web, old_pointer["operations"])

        import_capture(data, second_source, "2026-11-13", "backfill")
        check(
            "archiving_new_capture_does_not_publish_it",
            pointer_path.read_bytes() == old_pointer_bytes,
        )

        process = subprocess.Popen(
            [sys.executable, "-c", WORKER, str(data), str(web), str(ready)],
            cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 15
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            check("observed_atomic_verified_candidate_barrier", ready.exists())
            candidate = read_json(ready)
            candidate_verified = verify_edition(data, web, candidate)
            check(
                "candidate_independently_replays_two_captures_and_two_notices",
                candidate_verified["captures"] == 2
                and candidate_verified["notices"] == 2
                and candidate_verified["replay_from_empty"],
            )
            check("candidate_has_a_new_release", candidate["release"] != old_pointer["release"])
            check(
                "candidate_has_a_new_operations_ledger",
                candidate["operations"] != old_pointer["operations"],
            )
            check(
                "old_pointer_still_served_at_barrier",
                pointer_path.read_bytes() == old_pointer_bytes,
            )
            check(
                "old_release_unchanged_at_barrier",
                asset(web, old_pointer["release"]) == old_release_bytes,
            )
            check(
                "old_operations_unchanged_at_barrier",
                asset(web, old_pointer["operations"]) == old_operations_bytes,
            )
            try:
                publish_edition(data, web)
                excluded = False
            except ContractError as exc:
                excluded = "Another publisher" in str(exc)
            check("competing_publisher_denied_while_child_holds_locks", excluded)

            recovery_started = time.perf_counter()
            process.kill()
            process.wait(timeout=5)
            check("worker_abruptly_terminated", process.returncode != 0)
            check(
                "old_pointer_bytes_survive_worker_death",
                pointer_path.read_bytes() == old_pointer_bytes,
            )
            check(
                "old_release_bytes_survive_worker_death",
                asset(web, old_pointer["release"]) == old_release_bytes,
            )
            check(
                "old_operations_bytes_survive_worker_death",
                asset(web, old_pointer["operations"]) == old_operations_bytes,
            )
            recovered, lock_release_observation = _publish_after_exit(data, web, process)
            check(
                "retry_publishes_after_process_owned_locks_release",
                recovered["status"] == "published",
            )
            recovered_verified = verify_edition(data, web)
            recovery_seconds = round(time.perf_counter() - recovery_started, 6)
            check(
                "recovered_edition_replays_from_empty",
                recovered_verified["captures"] == 2
                and recovered_verified["notices"] == 2
                and recovered_verified["replay_from_empty"],
            )
            recovered_pointer_bytes = pointer_path.read_bytes()
            recovered_pointer = json.loads(recovered_pointer_bytes)
            recovered_release_bytes = asset(web, recovered_pointer["release"])
            recovered_operations_bytes = asset(web, recovered_pointer["operations"])
            check(
                "retry_retains_candidate_release_identity",
                recovered_pointer["release"] == candidate["release"],
            )
            release = json.loads(recovered_release_bytes)
            observed_correction = next(row for row in release["notices"] if row["id"] == "101-2026")
            check(
                "correction_matches_independent_deadline_oracle",
                {
                    "field": "deadline",
                    "label": "Earliest reported lot deadline",
                    "before": "2026-12-01",
                    "after": "2026-12-15",
                }
                in observed_correction["comparison"]["changes"],
            )

            # Corrupt only this isolated synthetic archive. Even a semantic no-op
            # must fail its content address; restore the exact backed-up bytes.
            archived_source = data / read_json(data / "captures.json")["captures"][1]["path"]
            backed_up_source = archived_source.read_bytes()
            archived_source.write_bytes(backed_up_source + b"\n ")
            refused = []
            for action in (publish_edition, verify_edition):
                try:
                    action(data, web)
                    refused.append(False)
                except ContractError as exc:
                    refused.append("Archived source hash mismatch" in str(exc))
            check("source_corruption_blocks_publication", refused[0])
            check("source_corruption_blocks_replay_verification", refused[1])
            check(
                "source_corruption_preserves_current_pointer",
                pointer_path.read_bytes() == recovered_pointer_bytes,
            )
            check(
                "source_corruption_preserves_release_asset",
                asset(web, recovered_pointer["release"]) == recovered_release_bytes,
            )
            check(
                "source_corruption_preserves_operations_asset",
                asset(web, recovered_pointer["operations"]) == recovered_operations_bytes,
            )
            archived_source.write_bytes(backed_up_source)
            check(
                "restoring_exact_source_bytes_restores_replay",
                verify_edition(data, web)["status"] == "verified",
            )
            check(
                "repaired_archive_requires_no_new_release",
                publish_edition(data, web)["status"] == "unchanged",
            )
            check(
                "repair_preserves_consumer_pointer_bytes",
                pointer_path.read_bytes() == recovered_pointer_bytes,
            )
            report = {
                "schema_version": 1,
                "started_at": started_at,
                "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "scope": (
                    "Actual local subprocess termination and hash-corruption exercise over two "
                    "synthetic notices; not a TED outage, cloud test or service SLA."
                ),
                "fixture_kind": "synthetic",
                "source_fixture_sha256": [digest(initial), digest(correction)],
                "code_sha256": code_fingerprint(),
                "runtime": {"python": platform.python_version(), "platform": platform.platform()},
                "observed_boundary": (
                    "Immutable release and operations assets passed replay verification; "
                    "the child atomically signaled its candidate pointer before promotion. "
                    "The parent independently verified that candidate, then killed the child."
                ),
                "worker_exit_code": process.returncode,
                "lock_release_observation": lock_release_observation,
                "previous_bundle": {
                    "pointer_sha256": sha(old_pointer_bytes),
                    "release_sha256": sha(old_release_bytes),
                    "operations_sha256": sha(old_operations_bytes),
                },
                "candidate_bundle": candidate,
                "recovered_bundle": {
                    "pointer_sha256": sha(recovered_pointer_bytes),
                    "release_sha256": sha(recovered_release_bytes),
                    "operations_sha256": sha(recovered_operations_bytes),
                },
                "source_repair": {
                    "original_sha256": sha(backed_up_source),
                    "corrupt_sha256": sha(backed_up_source + b"\n "),
                    "method": "Restored exact source bytes backed up inside the isolated exercise",
                },
                "previous_notice_count": 1,
                "recovered_notice_count": 2,
                "recovery_seconds": recovery_seconds,
                "recovery_measurement": (
                    "Local kill request through successful retry and replay verification"
                ),
                "wall_seconds": round(time.perf_counter() - started, 6),
                "checks": checks,
                "passed": len(checks),
                "failed": 0,
                "limits": [
                    "Fixture dates describe synthetic input; observation times above are real.",
                    "One atomic local pointer; no multi-region or CDN consistency claim.",
                    "Abrupt process death before promotion is tested; host power loss is not.",
                    "Verified orphan assets may remain; readers follow only current.json.",
                    "OS advisory locks coordinate only publishers using this implementation.",
                    "Local timings are observations, not performance or availability targets.",
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = run_exercise(args.output)
    except (ContractError, OSError, subprocess.SubprocessError) as exc:
        print(f"Edition exercise refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
