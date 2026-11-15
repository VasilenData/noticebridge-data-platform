# Source selection and field meaning

## Captured population

The frozen `data/source_snapshot.json` was collected on **15 November 2026** from
the European Union Publications Office's public TED Search API. Its exact UTC
capture time and collector hash are recorded in the artifact.
It contains **229 primary notices** matching:

```text
publication-date = 20261113 AND classification-cpv = 72000000
```

The CPV query is hierarchical, as evaluated by TED. These are published notices
of several types, including calls, results and modifications. They are **not 229
open opportunities**, all European IT procurement, or all notices on TED.

The collector requests the `ALL` scope with `onlyLatestVersions=false`. It uses
the API's `ITERATION` mode, validates each reported population, checks unique
publication numbers, requires the terminal empty page and reconciles the final
count. The complete primary query took four responses: 100, 100, 29 and 0 notices.
An interrupted, timed-out, duplicate or incomplete selection cannot replace the
last source snapshot. A later context lookup returning changed selected fields
for an already captured publication also aborts instead of silently keeping or
replacing one version.

The capture also contains **72 context notices** reached through explicit
correction references, for at most two hops. **Five older references remain
unresolved within that bound** and remain visible. Context rows are historical
evidence, separate from the primary query population. This is one frozen capture,
not a claim of daily operation or a complete history of every procedure.

## Multi-partition backfill captured on 15 November

The next collection run retrieved five distinct publication-day partitions, using
the same IT-services query and the same two-hop context bound. The dates below
are **publication dates**; every capture actually ran on **15 November 2026**.
They do not represent five days of unattended operation.

| Publication partition | Primary notices | Context notices | Unresolved references | Capture started (UTC, 15 Nov) |
| --- | ---: | ---: | ---: | --- |
| 2026-11-09 | 274 | 78 | 10 | 14:20:48 |
| 2026-11-10 | 217 | 76 | 9 | 14:21:00 |
| 2026-11-11 | 226 | 52 | 6 | 14:21:19 |
| 2026-11-12 | 204 | 61 | 13 | 14:21:38 |
| 2026-11-13 | 229 | 72 | 5 | 14:21:55 |

The last collection completed at 14:22:11 UTC. Each primary population reconciled
to the terminal empty page, and five correction notices per partition passed the
six selected API/XML checks: **150 comparisons across the new captures**.

Together with the original frozen capture, these inputs contain **1,457 unique
publication IDs**, including **1,150 unique primary IDs**. There are **322 IDs
seen in more than one input**, and no conflicting selected-source-field hashes
were observed for those repeated IDs. Summing all input rows would double-count
both context and the repeated 13 November selection.

The new capture requests encountered **15 real HTTP 429 responses**. Their
recorded bounded waits and subsequent successful attempts are visible in each
capture's request evidence. This is observed recovery from rate limiting during
one backfill session, not a service availability metric.

## Meaning of each field

| Output | TED source | Interpretation |
| --- | --- | --- |
| `notice_id` | `publication-number` | Public publication identity, such as `789562-2026`. |
| `publication_date` | `publication-date` | Calendar date. A source suffix such as `+01:00` is retained in provenance; this is not converted into an invented midnight-UTC timestamp. |
| `title` | `notice-title` | TED's English display title where supplied; the original procurement wording can remain in another language. No machine translation is added. |
| `buyer` | `buyer-name` | Published buying-organization label. No name-based entity resolution or inferred identity. |
| `countries` | `organisation-country-buyer` | ISO alpha-3 buyer-organization countries. These do not establish place of performance, supplier eligibility or remote delivery. |
| `cpv_codes` | `classification-cpv` | Distinct codes reported anywhere in the notice. No claim that every lot has each code. |
| `deadline` | `deadline-receipt-tender-date-lot` | Earliest reported lot calendar date, explicitly labelled as such. It does not establish open/closed status or one universal notice deadline. |
| `deadline_dates` | Same | Every distinct reported lot date, sorted. The API selection does not map each date to a lot identifier. Original values remain in `source_refs`. |
| `notice_type` | `notice-type` | Raw source code, preserved rather than replaced by an inferred procurement status. |
| `previous_notice_ids` | `change-notice-version-identifier` only | An explicit correction pointer, resolved to a publication number where the captured context supports it. Unresolved source pointers remain visible. |

`previous-notice-id-proc` can link different stages of a procurement procedure,
such as an award and its earlier call. `modification-previous-notice-identifier`
can link contract modifications. Both are retained separately in `source_refs`;
**neither becomes a correction edge**.

A correction pointer may be a publication number or a notice UUID with a version
suffix. The collector resolves the latter by an exact UUID-and-version query.
Conflicting aliases fail closed; names or similar titles never substitute for an
explicit reference.

## Published XML comparison

Five primary notices containing explicit corrections were fetched separately in
their published XML representation. Six selected checks per notice compared:
notice UUID, version, type, publication date, explicit correction pointer, and the
set of reported tender-submission lot dates. **All 30 comparisons passed.**

This is cross-representation reconciliation against the same publisher, not an
independent source, a full semantic validation or a statistical accuracy estimate.
The snapshot records each source URL, XML byte count, SHA-256 and selected values.
Full XML bodies are not retained or published because they can contain contact
details outside this product's purpose.

### Inspectable real change

[789562-2026](https://ted.europa.eu/en/notice/-/detail/789562-2026), published on
13 November, explicitly points to the notice/version resolved as
[706866-2026](https://ted.europa.eu/en/notice/-/detail/706866-2026), published on
13 October. Both concern “IT services for Digital Health” for the Icelandic buyer
Fjársýsla ríkisins. The captured earliest reported lot date changes from
**18 November to 25 November 2026**. The newer publication's XML confirms its
explicit predecessor and the 25 November date.

This is an observed change between published records. It is not evidence that a
supplier received an extension, won work, or met procurement eligibility rules.

## Provenance and privacy

- The request uses a fixed allowlist of organization, identifier, classification,
  title and date fields. It excludes email, phone, street and person/contact fields.
- Every normalized row retains the selected source fields and their canonical
  JSON SHA-256; the full API-response byte hashes are also recorded. New captures
  also include canonical request-body hashes and each HTTP attempt's observation
  time, duration, status and retry wait where relevant.
- The final collector's LF-normalized source hash is stored in the evidence.
- Raw XML is processed in memory, reduced to selected identifiers/dates, and
  discarded. Its hash supports comparison with the public original.
- The public app should consume the compact generated release, while this frozen
  selected-field capture supports local reproduction and review.

## Reproduce a new collection

```sh
python sources/collect.py --publication-date 2026-11-13 --output local-evidence/source-new.json
```

The collector limits primary queries to 1,000 notices and additional context to
160 notices. Narrow the query if those limits are exceeded. It retries selected
transient responses up to three attempts, with a 20-second socket timeout and
bounded waits. Longer or unsupported `Retry-After` instructions fail closed.
These socket timeouts are not an OS-level wall-clock termination guarantee.

Both standard `Retry-After` forms are supported: integer seconds and an HTTP date.
A wait above ten seconds or a malformed instruction aborts collection. Permanent
HTTP errors are not retried. Retries do not increase the three-attempt ceiling.
The recorded attempt duration excludes the separately reported retry wait.

For a controller that collects several partitions, use
`sources.collect.collect_day("YYYY-MM-DD")`. It adds the requested publication
date to source metadata and verifies that every primary row belongs to that day;
historical context is explicitly exempt. Invalid page totals, malformed publication
identifiers, repeated/missing iteration tokens, and rows exceeding the reported
population fail closed. Context depth is limited to an integer from zero to four.

A verified zero-row query is a successful observation of an empty partition,
which can occur on weekends or holidays. Its check time must not be confused with
the date of the newest published notice. Retain both values in operating reports.

Use a new output path to retain the published capture. Future API results may
differ; a successful new collection does not retroactively change the old record.

## Primary references

- [TED Search API](https://docs.ted.europa.eu/api/latest/search.html)
- [Pagination, iteration and response limits](https://docs.ted.europa.eu/ODS/latest/reuse/search-api.html)
- [Official OpenAPI schema](https://api.ted.europa.eu/api-v3.yaml)
- [TED data reuse and notice formats](https://docs.ted.europa.eu/ODS/latest/reuse/index.html)
- [Public XML for the observed correction](https://ted.europa.eu/en/notice/789562-2026/xml)
