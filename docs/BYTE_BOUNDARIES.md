# Verify the bytes that are actually consumed

## Reproduced problems and changes — 15 November 2026

The archive reader previously hashed a file, closed it, then reopened it to parse
JSON. A controlled replacement between those reads made it return a changed title
under the original source fingerprint. The regression now verifies that hashing
and parsing consume one bounded byte buffer. A subsequent read rejects the changed
on-disk file. This prevents that two-read identity error; it is not a claim that
ordinary filesystem reads are transactions against arbitrary concurrent writers.

The old size guard checked `stat()` before an unbounded text read. Reads now request
at most 64 MiB plus one sentinel byte and refuse excess bytes before JSON decoding.
The same guard covers imports and immutable published assets. Duplicate keys,
non-object roots and non-finite values, including exponent overflow such as `1e309`,
are refused. Generated immutable assets also have to fit the consumer limit.

The edition verifier previously accepted a rehashed operating ledger claiming 100
remaining slots after one capture. It now derives capacity from the verified index.
The browser separately checks remaining capacity and conservation of new,
seen-again and retained identities across every historical edition. Hash equality
alone is not semantic reconciliation or publisher authentication.

A fresh Windows clone exposed line-ending conversion of fingerprinted source files.
`.gitattributes` now preserves JSON bytes and uses LF for text code. Archived source
files and previous published editions remain unchanged; the six captures still
represent observations collected on one day.

## Reproduce the proof

```sh
pytest -q tests/test_byte_boundaries.py
node --test web/test-ui.mjs
python -m noticebridge.operations verify
python -m noticebridge.edition_exercise --output local-evidence/new-byte-boundary-recovery.json
```

The complete local suite passed **119 Python tests and 14 JavaScript tests**.
The [dated recovery exercise](byte-boundary-recovery-2026-11-15.json) passed 26
checks against synthetic fixtures. Current real-data editions were regenerated
from the unchanged six original captures with the updated compiler; no new source
observations or hosted-collection success are implied. TED's hosted access challenge
and disabled schedule remain documented in [Operations](OPERATIONS.md).

Implementation and review are AI-assisted. These are reproducible correctness and
recovery checks, not human peer review or production availability evidence.
