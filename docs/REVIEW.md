# Delivery review — 15 November 2026

This was an AI-assisted implementation and adversarial review, not independent
human peer review. Findings were fixed before the initial public release.

| Counterexample | Correction and evidence |
|---|---|
| A capture claims complete coverage but contains one of two reported primary records. | Require an exact integer population/count reconciliation before publication; regression rejects mismatches and unknown totals. |
| A later correction-context request returns different selected fields for an already captured publication. | Compare the selected source fields before deduplication; abort the collection and preserve the previous source snapshot. |
| A child's original UUID parent is unresolved in one capture and becomes available later. | Preserve the raw correction pointer as source identity; derive resolution against the combined retained history. |
| A later lot deadline changes while the earliest deadline is unchanged. | Retain and compare the full reported date set; never infer its association to individual lots. |
| The parent observes a readiness filename before the child has finished writing its contents. | Publish the readiness marker atomically before the parent reads it and terminates the worker. |

The final source was recollected using the fixed collector. The release was rebuilt
from that frozen capture, reproduced byte-for-byte into a fresh output, and checked
against its source and code fingerprints. The source representation checks cover
five actual published XMLs; the interruption tests use synthetic fixtures.

Known limits remain in the UI, README, source contract and engineering decisions.
No claim of production adoption, managed-cloud deployment or sustained operation
was added. CV promotion remains gated on stronger evidence over time.

## Flagship extension review

The next review addressed reconstructible history and a coherent consumer edition.
It was also AI-assisted, not an external human endorsement.

| Counterexample | Fixed boundary |
|---|---|
| A checksummed output supplies its own retained history to the verifier. | Archive original captures and reconstruct every edition from empty state; missing or changed historical input fails verification. |
| A recomputed checksum conceals an impossible first/last-seen timestamp. | Validate explicit UTC clocks, first ≤ last ≤ capture, and current/retained scope semantics. |
| A conflicting recapture or cross-capture cycle enters the index and poisons every subsequent replay. | Replay the entire candidate batch before atomically accepting the index; rejected batches leave both index and public pointer unchanged. |
| Another importer advances the index between verification and promotion. | Hold archive and publication locks through verification and pointer replacement; competing import is rejected. |
| Data publishes but its operating ledger still describes another edition. | Immutable data and ledger are verified before one pointer selects both. The browser checks downloaded hashes. |
| A terminated Windows worker has exited but its file lock is briefly still unavailable. | Probe recovery immediately after observed exit; retry only actual lock contention under a five-second deadline, recording each probe. No guessed pre-kill sleep. |
| A staging subdirectory contains an unmanifested file. | Recursively check the exact static allowlist before packaging. |
| A PR replaces pending production work or an older rerun deploys over newer code. | Isolate non-main concurrency and reject deployment when its SHA is no longer main. |

The expanded local regression suite passed **112 Python tests and 12 JavaScript
tests**. The [complete-edition recovery exercise](edition-recovery-2026-11-15-final.json)
passed **26 observed checks** using synthetic fixtures, including controlled child
termination, preservation of both previous assets, retry and exact archived-source
repair. Earlier receipts are retained as dated iterations, with their own code hashes.

Real-source observations are separate: the six captures include 17 HTTP 429 responses
recovered by bounded retries and 180 selected API/XML checks. Historical publication
partitions were collected today; they do not establish historical operating uptime.

The first hosted refresh exposed an empty XML response. Follow-up regressions keep
HTTP and content failures inside one three-attempt budget, preserve terminal
response diagnostics, and refuse explicit access challenges without bypass.
API/XML disagreements still fail. Review also found encoding-dependent DTD
rejection; the parser now refuses doctypes directly, including UTF-16 input.
The collector subset passes 40 tests. See the dated incident in [Operations](OPERATIONS.md).
