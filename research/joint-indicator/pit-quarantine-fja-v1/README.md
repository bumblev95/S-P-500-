# FJA membership candidate quarantine

**Audit-only. All 34 legacy origins remain blocked (0/34 ready).** This additive
bundle does not modify `pit-inputs-v1`, any prior study, or production. It has no
PIT `inputs.json`, provider certification, training, price collection, cohort
export, promotion or scheduled job. All candidate `historicalKnownAt` and
`securityId` values are null. Tickers are comparison tokens, not security IDs.

The source is [fja05680/sp500](https://github.com/fja05680/sp500/tree/a2430f2af0c79ddf0748e91de11bdeb1616ab5a7),
pinned at `a2430f2af0c79ddf0748e91de11bdeb1616ab5a7`. The comparison reference is
PR #25 head `dd84d24dc44eaf6dee6afaad7b3828ac737e2086`.

## Reproduce

From the repository root, using Python 3.11+ and only the standard library:

```sh
python -m unittest discover -s scripts -p test_fja_sp500_quarantine.py -v
python scripts/audit_fja_sp500_quarantine.py --verify
python scripts/build_pit_sp500_inputs.py --verify
python scripts/audit_fja_sp500_quarantine.py --export-cohorts
python scripts/build_pit_sp500_inputs.py --export-cohorts
```

The two export commands **must exit 2 without a cohort file**. A passing audit
means the evidence and blocked decision replay, not that the dataset is ready.
`--verify` uses saved bytes, no network or installed vendor access. The separate
read-only workflow has no schedule, branch writes, model jobs or source downloads.

The one-time importer reads Git objects from a local clone, never executes its
notebooks, and requires the explicit pinned commit:

```sh
python scripts/audit_fja_sp500_quarantine.py --import-source \
  --source-repo /absolute/path/to/sp500 \
  --source-commit a2430f2af0c79ddf0748e91de11bdeb1616ab5a7
python scripts/audit_fja_sp500_quarantine.py --audit
```

An existing source lock is verified, not reacquired or replaced. Different
upstream commits require a new version. Frozen output writes preflight the whole
write set and refuse differing bytes. `--folder` permits an isolated new bundle;
it does not enable PIT export. Audit gzip verification compares canonical
decompressed bytes to avoid Python/zlib header differences.

## Provenance and outputs

| File | Contents |
|---|---|
| `source-lock.json` | Commit, root tree, per-file Git blob SHA-1, raw/stored SHA256, acquisition timestamp, source locators, 48 preserved reference-file hashes |
| `sources/commit.git-object`, `sources/tree.git-object` | Raw Git objects; recompute their object IDs and prove each source blob belongs to the pinned commit |
| `sources/*.gz` | Exact unmodified source bytes compressed locally: five CSVs, README, MIT license and four explanatory notebooks |
| `observations.json.gz` | 1,534 ticker/action/day candidates, CSV record locators and per-candidate official comparison |
| `coverage-audit.json` | Explicit match/conflict/unconfirmed partitions, official-notice provenance, cross-file issues and every origin's baseline/change window/blockers |
| `origin-coverage.csv` | Reviewable 34-row baseline/change coverage summary |
| `FINDINGS.md` | Korean findings and remaining evidence gaps |
| `UPSTREAM-LICENSE.txt` | Original MIT copyright and permission notice |

The lock preserves the payload retrieval clock separately from historical
availability. Neither the source Git commit date, a CSV observation date nor an
origin date is assigned as a historical publication clock. A later download of
a revised historical list cannot certify what was knowable at the origin.
Source file/record locators resolve through the lock's immutable blob URLs.
Official locators, bytes and clocks remain in the frozen reference bundle.

## Comparison rules

- At an origin, select the latest candidate snapshot date **at or before** the
  origin, only inside the actual payload date range. This is retrospective
  coverage inspection, never a tradable cohort. A same-day row retains an
  intraday-timing warning. No historical publication time is fabricated.
- Retain dot/hyphen spelling, share-class tokens, repeated membership spells and
  original suffixed tokens. Fail on malformed, duplicate or unsorted input.
  Never splice ticker histories or infer permanent IDs, CIK linkage or returns.
- Derive ticker changes from adjacent snapshots; compare explicit changes and
  interval boundaries independently as artifacts of the **same upstream lineage**.
  Interval ends are exclusive; first observations and open-ended intervals are
  censored, not proof of entry/exit or indefinite continuation.
- Official membership matches require identical ticker, action and effective
  day, using the symbol observation in that same official notice. Same-day
  opposite actions or same-direction dates within seven calendar days are
  explicit conflicts, not fuzzy matches. Missing comparators and more distant
  events are unconfirmed; no event is invented from silence. Conflicts take
  precedence over matches. The window detects nearby discrepancies only.
- Per-origin official comparisons apply both existing `knownAt < session open`
  and `effectiveAt <= session open`. Later notices cannot validate earlier
  baselines. The last seeded membership fact is a limited state comparison,
  not evidence of complete subsequent changes. Unsupported sector, alias and
  delisting facts remain separately unconfirmed.
- Origin change windows run from the preceding requested origin (exclusive) to
  this origin (inclusive); the first starts at the first source snapshot.
  Missing pre-2019 explicit-ledger coverage is flagged. Counts include observed
  events only and never certify a quiet interval as complete.

## Limits that remain binding

The pinned README describes pre-2019 data obtained with *Trading Evolved*, later
manual Wikipedia/search updates, incomplete selected changes, and the need for
separate delisted-price data. It also proposes treating ticker renames as sales;
that suggestion is **not** adopted here. Its reconstruction notebook strips
`-yyyymm` suffixes and deduplicates symbols. The audit records every original row
where stripping collapses tokens; those counts are not counts of confirmed
missing securities. Notebook replay is a diagnostic explanation, not a repair
or independent identity certificate. Current `sp500.csv` is archived solely for
lineage and is never used for historical membership or sectors.

All origins still require complete security-level membership baselines/change
evidence, historical sectors and their taxonomy/vintages, permanent identity and
dated alias continuity, original price vintages including delisted securities,
resolved full-lifecycle outcomes, and original publication/revision evidence.
WBA contingent rights remain unresolved in the reference. No final return is
calculated from removal dates, the last price, headline cash or a successor.

Local validation: 36 new regressions plus the existing 60 pass (96 total).
The new CI job runs the 36 new and 32 existing PIT tests (68, stdlib only),
replays both audits, checks all 48 preserved hashes and verifies both failed
exports. Earlier model tests require the project's NumPy/scikit-learn stack;
they were run locally without regenerating any study.
