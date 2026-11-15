"""Synthetic failure and competing-writer exercises, independent of live API uptime."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_engine import notice, snapshot

from noticebridge.engine import ContractError, canonical
from noticebridge.publish import build_to_path, verify_path


def write_source(path, *records, **kwargs):
    path.write_bytes(canonical(snapshot(*records, **kwargs)))


def test_incomplete_source_cannot_replace_previous_release(tmp_path):
    source, output = tmp_path / "source.json", tmp_path / "data.json"
    write_source(source, notice())
    build_to_path(source, output)
    original = output.read_bytes()
    incomplete = snapshot(notice(), notice("101-2026"))
    incomplete["source"]["coverage"]["complete_for_selection"] = False
    source.write_bytes(canonical(incomplete))
    with pytest.raises(ContractError, match="Incomplete"):
        build_to_path(source, output)
    assert output.read_bytes() == original


def test_failed_validation_and_staging_failure_preserve_bytes(tmp_path):
    source, output = tmp_path / "source.json", tmp_path / "data.json"
    write_source(source, notice())
    build_to_path(source, output)
    original = output.read_bytes()
    write_source(source, notice(title="Changed immutable publication"))
    with pytest.raises(ContractError):
        build_to_path(source, output)
    assert output.read_bytes() == original
    write_source(source, notice(), notice("101-2026"))

    def fail_after_write(staged):
        assert json.loads(staged.read_text())["summary"]["notice_count"] == 2
        raise RuntimeError("controlled interruption after validated stage")

    with pytest.raises(RuntimeError, match="controlled interruption"):
        build_to_path(source, output, before_replace=fail_after_write)
    assert output.read_bytes() == original
    assert not list(tmp_path.glob(".data.json.*.tmp"))
    assert build_to_path(source, output)["status"] == "published"
    assert verify_path(source, output)["status"] == "verified"
    assert build_to_path(source, output)["status"] == "unchanged"


def test_abrupt_process_death_after_staged_write_preserves_old_release_and_unlocks(tmp_path):
    source, output, ready = tmp_path / "source.json", tmp_path / "data.json", tmp_path / "ready"
    write_source(source, notice())
    build_to_path(source, output)
    original = output.read_bytes()
    write_source(source, notice(), notice("101-2026"))
    script = """
import os, sys, time
from pathlib import Path
from noticebridge.publish import build_to_path
def barrier(staged):
    marker = Path(sys.argv[3])
    temporary = marker.with_suffix('.tmp')
    temporary.write_text(str(staged), encoding='utf-8')
    os.replace(temporary, marker)
    while True:
        time.sleep(1)
build_to_path(Path(sys.argv[1]), Path(sys.argv[2]), before_replace=barrier)
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(source), str(output), str(ready)],
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), proc.communicate(timeout=2)
        staged = Path(ready.read_text())
        assert json.loads(staged.read_text())["summary"]["notice_count"] == 2
        with pytest.raises(ContractError, match="Another publisher"):
            build_to_path(source, output)
        assert output.read_bytes() == original
        proc.kill()
        proc.wait(timeout=5)
        assert proc.returncode != 0
        assert output.read_bytes() == original
        assert build_to_path(source, output)["status"] == "published"
        assert json.loads(output.read_text())["summary"]["notice_count"] == 2
        assert verify_path(source, output)["status"] == "verified"
        # An abrupt process death may leave a complete orphan stage, never a partial public file.
        assert staged.exists()
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=5)


def test_cli_reports_failure_without_success_json(tmp_path):
    source, output = tmp_path / "source.json", tmp_path / "data.json"
    source.write_text('{"schema_version": 2}', encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "noticebridge",
            "build",
            "--source",
            str(source),
            "--output",
            str(output),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "Publication refused" in proc.stderr
    assert proc.stdout == ""
    assert not output.exists()
