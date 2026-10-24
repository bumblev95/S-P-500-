# Public historical notice supplementation — research only

This is a separate, additive input bundle stacked on PR #25 at
`1aa16f7a831b0aeed411593fe64464af94115cd5`. The existing PIT, FJA, lifecycle,
drawdown and forecast studies are unchanged. PR #54 at
`48a99f03045f80a39a36aed6b308ecde4894b1c2` remains a separate required guard;
this input work does not merge, replace, release or modify it. Before integration
into main, retain both dependencies and review the combined tree. This draft
targets the PR #25 branch so its diff contains only the evidence addition.

**PIT readiness: 0/34. Lifecycle readiness: 0/34. Computed outcomes: 0.**
No full cohort, fitted model, performance score, final shareholder return, paid
entitlement, production import or deployment is created.

## Concrete additions

- Reuse all five existing PIT source payloads, the existing origins, FJA candidate
  records and the unresolved WBA observation. Preserve SHA256 of all 1,155
  reference-branch files. Do not reinterpret the candidate ticker snapshots as
  historical universes.
- Add 62 individual S&P 500 membership table facts from 18 official notices,
  with row locators, exact saved capture hashes, publication dates, conservative
  original knowledge floors and independent session-open effective clocks.
  There are now 70 official notice membership facts including the eight seeds.
- Compare all 1,534 preserved candidate records: **68 match, 2 conflict,
  1,464 unconfirmed**. This is ticker/action/day corroboration only. It does
  not certify permanent issue identity, missing-change completeness, candidate
  historical availability or a full origin population.
- Save issuer/class observations for COIN, DFS and PSKY, their filing index
  dates and SEC accession locators. CIK/class observations stay outside verified
  PIT identity events. All 69 local issue placeholders remain provisional.
- Normalize Solventum's explicit sector footnote into two separate events:
  Industrials from April 1, 2024 pre-open, Health Care from April 3 pre-open.
  The table's `Health Care*` label is never backfilled to April 1.
- Preserve GICS 2023 structure changes and the June 2022 select-list release as
  diagnostic observations. The latter says classifications remained subject to
  review; the final client company map was not obtained. No final Visa,
  Mastercard or other company sector is guessed from a structure announcement.
- Save Discover closing/exchange/delisting and Paramount predecessor/successor,
  election and proration documents, plus Ansys closing evidence, as unresolved
  lifecycle observations. No completed accounting action or successor price
  substitution is generated. WBA's contingent rights remain unresolved.

## Priority origins

The priority was selected from the original 34 requests, using short candidate
change windows and accessible official/issuer documents, not model outcomes.

| Origin | Priority | Candidate changes since preceding origin | Match / conflict / unconfirmed | Full input ready |
|---|---:|---:|---|---|
| 2025-02-07 | 1 | 8 | 8 / 0 / 0 | No |
| 2025-04-25 | 1 | 8 | 8 / 0 / 0 | No |
| 2024-10-11 | 2 | 18 | 16 / 0 / 2 | No |
| 2025-10-31 | 2 | 20 | 18 / 0 / 2 | No |
| 2023-03-24 | 3 | 6 | 4 / 0 / 2 | No |

Every match is individually filtered by `knownAt < origin open` and
`effectiveAt <= origin open`. The 2025 November Q/EMN facts saved in the October
notice cannot enter the October 31 origin. Quiet intervals and matching all
*candidate* window rows do not prove that the candidate omitted no changes.
No complete baseline or coverage attestation is supplied for any origin.

## Acquisition representation and limits

The 38 new saved acquisitions include 37 successful **web-extracted page
captures** and one failed FDIC fetch. They are exact saved tool-response bytes,
with retrieval clocks and SHA256, **not original HTTP HTML/PDF payloads**.
The source lock labels this representation and sets
`originalHTTPPayloadAvailable: false` and
`historicalRevisionVintageCertified: false` on every new acquisition. A direct
S&P page request returned HTTP 403; no access bypass was attempted. Duplicate
extracts/issuer release copies are retrieval records, not additional independent
membership corroborations. The FDIC failure is not a bank equity final recovery
certificate, and is excluded from normalized sources and events.

New normalized records use the unchanged schema's `dated_notice` tier solely
for individual observed facts and diagnostic previews. They **do not satisfy
the contract's original-payload/historical-revision requirement for a complete
PIT export**. Technical schema acceptance is not original-source certification.
The existing seed's saved HTML/PDF bytes are reused without alteration; their
previous archival-vintage and completeness limits still apply.

Publication is not inferred from an effective day or a SEC report period.
Date-only knowledge uses next America/New_York midnight. SEC accepted times
are retained as displayed; without separately certifying display timezone and
availability semantics, this bundle continues using conservative filing dates.
For example, the Coinbase report period is December 31, 2024, but the index
records February 13, 2025 filing, so this observation is not a 2024 feature.

## Files and offline replay

| File | Purpose |
|---|---|
| `source-lock.json`, `sources/` | Exact extraction/reused-payload provenance, failures, hashes, priority rationale and preserved-file lock |
| `membership-observations.json` | 62 official row facts; provisional lineage mapping notes and exact row text |
| `identity-observations.json`, `sector-structure-observations.json` | Observations ineligible as certified permanent identity or final company map |
| `inputs.json`, `origins.json`, `PROTOCOL.json`, `manifest.json` | New immutable bundle in the existing PIT schema; same 34 origins and disabled training/production |
| `lifecycle-inputs.json` | Unchanged lifecycle schema: six unresolved observations, no assets/actions/quotes/coverage |
| `coverage-audit.json` | Output of the original PIT auditor on the new bundle: blocked 0/34 |
| `supplemental-audit.json`, `origin-coverage.csv` | Full candidate partitions, notice locators, all 34 origin comparisons and remaining blockers |
| `FINDINGS.md` | Korean findings and next evidence dependencies |

From the repository root (Python 3.11+, standard library, no network):

```sh
python scripts/audit_public_pit_evidence.py --verify
python scripts/build_pit_sp500_inputs.py --folder research/joint-indicator/pit-public-evidence-v1 --verify
python scripts/build_pit_sp500_inputs.py --verify
python scripts/audit_fja_sp500_quarantine.py --verify
python scripts/build_merger_lifecycle.py --verify
python -m unittest discover -s scripts -p test_public_pit_evidence.py -v
```

The one-time `--build` normalizes saved observations only; it never downloads or
certifies them. It preflights output writes and refuses differing existing
bytes. Different final inputs require a new bundle. Implementation hashes are
also pinned in the manifest. The new read-only CI has no schedule, credential
provisioning, branch writer, model job or production deployment.

These exports **must exit 2 without creating output**:

```sh
python scripts/build_pit_sp500_inputs.py --folder research/joint-indicator/pit-public-evidence-v1 --export-cohorts
python scripts/build_merger_lifecycle.py --folder research/joint-indicator/pit-public-evidence-v1 --pit-folder research/joint-indicator/pit-public-evidence-v1 --export-outcomes --origin 2025-04-25 --target-at 2026-04-27T20:00:00Z --evaluated-at 2026-10-13T10:30:00Z --output /tmp/public-pit-outcomes.json
```

The explicit target timestamp above exercises the blocked gate; it is not a
claimed validated exchange-calendar horizon for a new experiment.
