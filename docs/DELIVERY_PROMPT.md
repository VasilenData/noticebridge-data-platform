# NoticeBridge delivery brief

This task-specific prompt adapts the specification → implementation → verification
discipline described by [GitHub Spec Kit](https://github.com/github/spec-kit),
especially its [specification prompt](https://github.com/github/spec-kit/blob/main/templates/commands/specify.md).
It uses the local data-engineering delivery skill for contracts, reconciliation,
failure tests and evidence. Spec Kit was a researched reference, not an installed
dependency. No prompt can establish production use, user adoption or engineering
seniority by itself.

## Prompt used for this delivery

Build NoticeBridge, an inspectable public-procurement change intelligence product.
A supplier should be able to find relevant public notices, inspect the original
source and understand what an explicitly linked correction changed. Deliver
working code and a polished read-only interface under a zero-paid-cloud constraint.

First inspect the official TED API documentation and a bounded actual response.
Define notice identity, publication and observation clocks, available parent
references, date semantics, optional values, and exactly what the sample covers.
Use real source publications. Keep fabricated failure scenarios in labelled tests.

Preserve provenance and build deterministically. Distinguish publication IDs from
internal notice IDs. Compare a correction only with an explicit parent found in
the snapshot. Do not infer a revision relationship from similar titles or invent
missing original values. Expose unresolved parent references and unavailable data.
Use explainable supplier filters; do not imply that relevance predicts an award.

Use the smallest maintainable stack that satisfies the contract. Avoid decorative
infrastructure. Bound network work and fail closed on a partial collection. Stage
and validate a complete consumer release before publishing it. Prove replay,
conflicting identities, missing parents, malformed sources and failure preservation
with small independently understandable fixtures. Record source, code, runtime,
observed outcomes and limitations together.

Design a clear product workflow rather than a technology showcase: browse, filter,
inspect, compare and follow the source. Use the portfolio's charcoal/mint palette,
readable type, keyboard navigation, mobile layouts and visible freshness/scope.
Use text-safe rendering and allowlisted source links. CSV exports must be safe to
open as text in spreadsheets. Empty and unavailable states must be useful.

Review the completed system against the contract; repair actual failures. Validate
the Python pipeline, browser behavior, links and final deployed bytes. Publish a
read-only demo and source, with a short technical explanation and reproducible
commands. Keep the existing three CV flagships until this project earns replacement
through measured functionality and operating history. Never fabricate customers,
business savings, a human review, continuous uptime or the owner's unaided work.

## Primary source references

- [TED Search API](https://docs.ted.europa.eu/api/latest/search.html)
- [Search modes and bounds](https://docs.ted.europa.eu/ODS/latest/reuse/search-api.html)
- [Published notice formats](https://docs.ted.europa.eu/ODS/latest/reuse/index.html)
- [Python atomic replacement API](https://docs.python.org/3/library/os.html#os.replace)

AI-assisted implementation and review. Dated evidence describes what ran; source
code alone does not establish that a service was operated.
