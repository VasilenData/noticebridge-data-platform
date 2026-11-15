# Capture, replay, publish and recover

## Two clocks, one verifiable history

`publication_day` identifies the queried TED partition. `captured_at` is the actual
UTC observation time. The November 9–13 partitions were backfilled on November 15;
they do not represent five days of operation. The public ledger shows both clocks.
`built_at` records when the current replay edition was built, and `duration_ms`
measures each local compiler step. Neither is network latency or an uptime measure.

Each original capture is retained byte-for-byte at `data/captures/<SHA256>.json`.
The ordered `data/captures.json` index records mode, date, time and hash. The
compiler starts from **empty state**, applies every capture, and regenerates every
historical consumer edition. It never uses the current output as evidence for
retained records. Missing or altered input prevents verification.

The edition selector shows reconstructions under the current compiler. It does not
claim those reconstructions were published at the earlier capture times. A compiler
change creates new identities; old public content-addressed files remain available.

## Publication boundary

The publisher holds the archive and consumer locks, replays the candidate, writes
immutable release files, and verifies every reconstructed edition. A single atomic
replacement of `web/current.json` selects **both** data and operations metadata.
An interruption before that replacement leaves the prior pair usable. Orphaned
candidate assets are harmless and do not become current. An invalid recapture or
cross-capture cycle is rejected before the source index changes.

This is an observed local filesystem visibility boundary. It is not a claim of
distributed transactions, instantaneous CDN invalidation or hardware power-loss
durability. The browser independently checks downloaded asset SHA-256 values.
Old hashed assets are retained so cached pointers remain resolvable across deploys.

## Commands

```sh
# Offline: reconstruct all historical editions from the archived inputs.
python -m noticebridge.operations verify

# Recollect one partition (an actual new observation, not backdated evidence).
python sources/collect.py --publication-date 2026-11-13 --output local-evidence/recapture.json
python -m noticebridge.operations import --source local-evidence/recapture.json --day 2026-11-13 --mode refresh
python -m noticebridge.operations publish

# Bounded rolling lookback: collect all requested days before accepting the batch.
python -m noticebridge.operations refresh --lookback 3

# Reproduce an actual synthetic process-interruption/source-repair exercise.
python -m noticebridge.edition_exercise --output local-evidence/new-edition-exercise.json
```

Importing the same frozen capture is idempotent. A new real recapture has a new
observation time and advances `last_seen_at`; it does not imply a new source notice.
Earlier publication-day backfills are allowed when observed later. Regressing
observation clocks, mutated immutable IDs, incomplete pagination and wrong-partition
primary rows are refused. Absence from a later query never means withdrawal.

## Refresh workflow and limits

The refresh command requests the preceding three UTC calendar days by default.
The GitHub workflow is manual-only after the observed hosted access challenge below;
the previously configured 07:23 UTC schedule was removed. Do not repeatedly run it
from the challenged environment. A permitted execution environment must first pass
the unchanged source checks before scheduling is restored.
It uses the public unauthenticated TED API and no paid database or cloud account.
Weekends/holidays may return a correctly completed zero-row partition. Successful
check time and newest publication date are separate; neither proves a notice is open.

After complete collection and replay, the workflow commits only capture/index and
generated release files as `github-actions[bot]`. It explicitly dispatches the
verification workflow on the new main head: a push made with `GITHUB_TOKEN` does
not itself trigger another push workflow. Tests, two recovery exercises, replay and
static packaging must pass before GitHub Pages deployment. Stale-head reruns refuse
deployment. Collection and main publication share a concurrency group; PR checks
have separate groups. Permissions are scoped to public repository content and
workflow dispatch; no new stored credential is required.

GitHub schedules may be delayed or dropped. Public repositories can also have
inactive scheduled workflows disabled. The browser exposes source freshness and
links to actual Actions results; no independent notification delivery or SLA is
claimed. A failed collection leaves the last public edition available.

The demonstration stops at **100 captures or 50,000 retained notices**. Six initial
captures leave 94 slots, roughly 31 three-partition refreshes. Capacity is visible
in the ledger. Exhaustion fails closed; do not delete historical captures silently.
Before raising these limits, measure replay time/storage and design an explicitly
versioned archive retention migration. Each input is limited to 64 MiB; collector
query/context/request limits remain in the source contract.

## Incident response

1. Inspect the failed Actions step and last successful pointer. Do not replace
   valid data with an empty placeholder or edit an archived publication to make a
   check pass. A genuine upstream change to an immutable ID requires a deliberate
   contract/version decision.
2. For damaged archived bytes, restore the **exact hash-matching source file** from
   Git history/backup. For a transient API failure, retry the bounded partition
   collection. Keep original observation times for restored bytes; newly fetched
   evidence receives its actual observation time.
3. Run independent archive replay, tests and the recovery exercise. Publish only
   after verification. Inspect the deployed hashes and source freshness.

## Observed hosted incident: 15 November 2026

The first manually dispatched three-day refresh,
[run 43726716227](https://github.com/VasilenData/noticebridge-data-platform/actions/runs/43726716227),
stopped at 14:52:59 UTC while parsing an empty XML response. The original logs did
not retain the response status/content type, so they do not establish why the
publisher returned no XML. This was a real upstream interaction, not a fault
injected exercise.

The batch had not been imported or committed. Main remained at
`8ece2dfa36c6b563fc946b7f40de62ea052fd630`; the publicly downloaded `current.json`
still matched the verified six-capture edition byte-for-byte. Its data asset was
`1a6e59d3b4307c748bc6c82ab83ae1dfc709bc8739a8a2c7d6a55e28c1ebd457`.
This establishes containment for this incident, not a successful hosted refresh
or a long-term availability record. The follow-up adds bounded response retries
and explicit diagnostics while keeping API/XML validation mandatory.

The instrumented follow-up,
[run 43727527685](https://github.com/VasilenData/noticebridge-data-platform/actions/runs/43727527685),
stopped at 15:02:00 UTC after **one** XML attempt. TED returned HTTP 202,
`Content-Type: text/html; charset=UTF-8`, zero bytes and
`x-amzn-waf-action: challenge`. The collector reported
`explicit_access_challenge_no_bypass`; it did not retry or use an alternate endpoint.
No batch was committed. This identifies the second failure as a hosted access
restriction, not malformed notice data. The original response lacked this telemetry,
so its cause remains unproven.

The workflow schedule is disabled. Existing local captures and independently
verified Pages publication remain usable. Resume automated collection only in a
permitted environment with the same XML validation gates; a hosted collection,
commit, dispatch and deployment cycle remains unverified end-to-end.

## References

- [TED iteration and pagination](https://docs.ted.europa.eu/ODS/latest/reuse/search-api.html)
- [GitHub schedule limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [Token-trigger behaviour](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)
- [Dagster partition backfills](https://docs.dagster.io/guides/build/partitions-and-backfills/backfilling-data)

These references informed the operating discipline. No additional orchestration
framework was installed; this bounded product uses Python and GitHub Actions.
