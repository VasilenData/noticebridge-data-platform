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
