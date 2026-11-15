"""Exercise the real local kill boundary and make false success impossible."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from noticebridge import edition_exercise as exercise
from noticebridge.engine import ContractError


def test_edition_recovery_receipt_records_observed_kill_replay_and_source_repair(tmp_path):
    output = tmp_path / "receipt.json"
    result = exercise.run_exercise(output)
    report = json.loads(output.read_bytes())
    checks = {check["name"]: check["passed"] for check in report["checks"]}
    assert result["status"] == "passed"
    assert report["fixture_kind"] == "synthetic"
    assert report["worker_exit_code"] != 0
    assert report["failed"] == 0
    assert all(checks.values())
    assert checks["old_pointer_bytes_survive_worker_death"]
    assert checks["old_release_bytes_survive_worker_death"]
    assert checks["old_operations_bytes_survive_worker_death"]
    assert checks["retry_publishes_after_process_owned_locks_release"]
    assert checks["recovered_edition_replays_from_empty"]
    assert checks["source_corruption_blocks_publication"]
    assert checks["source_corruption_blocks_replay_verification"]
    assert checks["restoring_exact_source_bytes_restores_replay"]
    assert (
        report["candidate_bundle"]["release"]["sha256"]
        == report["recovered_bundle"]["release_sha256"]
    )
    assert (
        report["previous_bundle"]["release_sha256"] != report["recovered_bundle"]["release_sha256"]
    )
    assert report["source_repair"]["original_sha256"] != report["source_repair"]["corrupt_sha256"]
    assert 0 < report["recovery_seconds"] <= report["wall_seconds"]
    assert report["lock_release_observation"]["probes"][-1]["status"] == (
        "published_after_lock_acquisition"
    )


def test_cli_refuses_to_overwrite_existing_evidence(tmp_path):
    output = tmp_path / "receipt.json"
    output.write_bytes(b"existing dated evidence")
    result = subprocess.run(
        [sys.executable, "-m", "noticebridge.edition_exercise", "--output", str(output)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "Evidence output already exists" in result.stderr
    assert result.stdout == ""
    assert output.read_bytes() == b"existing dated evidence"


def test_child_exit_before_verified_barrier_cannot_produce_a_success_receipt(monkeypatch, tmp_path):
    original_popen = subprocess.Popen

    def early_exit(*args, **kwargs):
        return original_popen([sys.executable, "-c", "raise SystemExit(7)"], **kwargs)

    monkeypatch.setattr(exercise.subprocess, "Popen", early_exit)
    output = tmp_path / "receipt.json"
    with pytest.raises(ContractError, match="observed_atomic_verified_candidate_barrier"):
        exercise.run_exercise(output)
    assert not output.exists()

    class ExitedWorker:
        @staticmethod
        def poll():
            return 7

    attempts = []

    def transient_lock(*args):
        attempts.append(1)
        if len(attempts) == 1:
            raise ContractError("Another publisher holds this output lock") from PermissionError(13)
        return {"status": "published"}

    monkeypatch.setattr(exercise, "publish_edition", transient_lock)
    result, observation = exercise._publish_after_exit(tmp_path, tmp_path, ExitedWorker())
    assert result["status"] == "published"
    assert observation["lock_denials_after_exit"] == 1
    assert [p["status"] for p in observation["probes"]] == [
        "lock_still_held",
        "published_after_lock_acquisition",
    ]

    def permanent_failure(*args):
        raise ContractError("Archived source hash mismatch")

    monkeypatch.setattr(exercise, "publish_edition", permanent_failure)
    with pytest.raises(ContractError, match="Archived source hash mismatch"):
        exercise._publish_after_exit(tmp_path, tmp_path, ExitedWorker())
