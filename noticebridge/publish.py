"""Single-writer, staged publication of one complete release payload."""

from __future__ import annotations

import json
import math
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .engine import ContractError, canonical, compile_release, validate_release

MAX_JSON_BYTES = 64 * 1024 * 1024


@contextmanager
def writer_lock(output: Path):
    """OS-owned advisory lock. Process death releases it; the sidecar is harmless."""
    lock_path = output.with_name(output.name + ".lock")
    handle = lock_path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        yield
    except OSError as exc:
        if not acquired:
            raise ContractError("Another publisher holds this output lock") from exc
        raise
    finally:
        if acquired:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def read_bytes_bounded(path: Path) -> bytes:
    """Read one observed payload; an earlier stat is not a read-time size bound."""
    with path.open("rb") as handle:
        raw = handle.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ContractError("Input exceeds the 64 MiB demonstration bound")
    return raw


def parse_json(raw: bytes, name: str = "input") -> dict:
    if len(raw) > MAX_JSON_BYTES:
        raise ContractError("Input exceeds the 64 MiB demonstration bound")

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ContractError(f"Repeated JSON object key: {key}")
            result[key] = value
        return result

    def no_constant(value):
        raise ContractError(f"Non-finite JSON number: {value}")

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            no_constant(value)
        return number

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_keys,
            parse_constant=no_constant,
            parse_float=finite_float,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ContractError(f"Invalid UTF-8 JSON: {name}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"JSON root must be an object: {name}")
    return value


def read_json(path: Path) -> dict:
    return parse_json(read_bytes_bounded(path), path.name)


def build_to_path(source: Path, output: Path, *, before_replace=None) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    with writer_lock(output):
        snapshot = read_json(source)
        previous = read_json(output) if output.exists() else None
        release = compile_release(snapshot, previous)
        data = canonical(release)
        if output.exists() and output.read_bytes() == data:
            return {
                "status": "unchanged",
                "release_id": release["release"]["id"],
                "notice_count": release["summary"]["notice_count"],
                "bytes": len(data),
            }
        staged: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False
            ) as handle:
                staged = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            validate_release(read_json(staged))
            if before_replace is not None:
                before_replace(staged)
            os.replace(staged, output)
            staged = None
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)
        return {
            "status": "published",
            "release_id": release["release"]["id"],
            "notice_count": release["summary"]["notice_count"],
            "bytes": len(data),
        }


def verify_path(source: Path, output: Path) -> dict:
    actual = read_json(output)
    validate_release(actual)
    expected = compile_release(read_json(source), actual)
    if output.read_bytes() != canonical(expected):
        raise ContractError("Published bytes do not reproduce from the source and retained history")
    return {
        "status": "verified",
        "release_id": actual["release"]["id"],
        "notice_count": actual["summary"]["notice_count"],
    }
