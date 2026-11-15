"""A dated real-source example with concrete expected facts, separate from simulations."""

import json
from pathlib import Path

from noticebridge.engine import compile_release


def test_recorded_iceland_correction_and_full_selected_population():
    path = Path(__file__).resolve().parents[1] / "data/source_snapshot.json"
    captured = json.loads(path.read_text(encoding="utf-8"))
    assert captured["source"]["query"] == (
        "publication-date = 20261113 AND classification-cpv = 72000000"
    )
    release = compile_release(captured)
    assert release["summary"]["primary_count"] == 229
    assert release["summary"]["context_count"] == 72
    assert release["summary"]["notice_count"] == 301
    rows = {row["id"]: row for row in release["notices"]}
    before, after = rows["706866-2026"], rows["789562-2026"]
    assert before["deadline"] == "2026-11-18"
    assert after["deadline"] == "2026-11-25"
    assert after["countries"] == ["ISL"]  # Buyer country; not delivery location.
    assert after["comparison"]["parent_id"] == "706866-2026"
    assert after["correction_refs"] == ["642c0588-c3e8-42fd-ab38-a32219067f0b-01"]
    assert {
        "field": "deadline",
        "label": "Earliest reported lot deadline",
        "before": "2026-11-18",
        "after": "2026-11-25",
    } in after["comparison"]["changes"]
    assert sum(row["comparison"]["status"] == "missing_parent" for row in rows.values()) == 5
