# Engineering decisions

## One source, multiple representations

TED's selected API fields and published XML represent the same provider's notices.
Comparing them is a representation check, not independent multi-source corroboration.
The initial product focuses on IT procurement notices and explicitly linked corrections.
It does not claim a complete procurement market, every tender document or legal advice.

## Exact corrections before entity matching

An explicit correction reference has a different meaning from a predecessor in a
procurement procedure. NoticeBridge does not turn similar titles, buyer names, or
award-to-competition links into a revision edge. Unresolved references remain visible.
Fuzzy entity resolution would require a reviewed evaluation set and measured error
costs; it is outside this first release.

## A small reproducible compiler

The source collector, validation/compiler and browser are separate. The public
consumer reads one complete JSON release, including its manifest and provenance.
No hosted database, cloud account, authentication or paid LLM is necessary for this
bounded workload. A new warehouse would add operational work without improving the
demonstrated question at this scale.

## Interpretability before a score

Supplier criteria are deterministic filters and reasons. A CPV/country/text match
does not establish eligibility, an open bidding period or probability of winning.
Publications can include results and changes to closed procedures. Readers must
inspect the source notice and its current official status before acting.

## Publication boundary

Validate the complete candidate before replacing the consumer JSON. Keep source
identity and stable release content reproducible. Process-interruption tests establish
the local file visibility boundary they actually exercise, not a distributed service
SLA or resilience to every hardware failure.

## Evidence and promotion

One source capture establishes a working integration and a dated observation. It
does not establish sustained operation. Synthetic adversarial tests remain labelled.
The portfolio keeps Meterwork, NYC Taxi and Finance Mart as its three featured CV
projects until a replacement has stronger observed evidence for the target role.

## Data attribution

Source: TED, Supplement to the Official Journal of the European Union, © European
Union. Derived fields are selected, normalized and compared by this project; these
are transformations, not original publisher statements. No TED logo is used.
The MIT license covers project code, not a relicensing of the source publications.
See [TED's reuse notice](https://ted.europa.eu/en/legal-notice) and SOURCES.md.
