# Normalized lifecycle provider contract

The engine is `scripts/research_merger_lifecycle.py`, using only the standard
library. It is not a downloader or a claimed CRSP/Norgate adapter. Raw provider
exports, original clocks, completeness evidence and permanent issue mappings
must be obtained separately. No credentials, subscription or entitlement are
assumed. The existing historical data blocker is unchanged.

Load with `LifecycleInputs.load(folder)`. `lifecycle-inputs.json` requires
`schemaVersion: 1`, `version: "shareholder-lifecycle-v1"`, matching `policyId`,
`researchOnly: true`, and the tables below. `sources` use the unchanged original
PIT source contract: exact saved payload bytes, SHA256, original availability
floor, actual retrieval, publication precision/provider clock semantics and
temporal quality. Current-only/quarantined evidence cannot enter records.

Every record references `sourceId`, explicit timezone-aware `knownAt` and
`effectiveAt`, and `evidenceLocator`. `knownAt` is never derived from the ticker,
effective day or current download time. Quotes and completed settlements cannot
be known before observation. Real in-memory inputs without payload verification
are rejected; synthetic fixtures require explicit test-only opt-in.

| Table | Required fields beyond source/clocks/locator | Meaning |
|---|---|---|
| `assets` | unique `securityId`, `kind: equity/right`, `verified`, `permanentId: {provider, scheme, value}`, `identityEvidence` | Scheme is PERMNO, GVKEY_IID or documented provider issue ID; ticker and CIK are insufficient. Unverified identities block accounting. |
| `actions` | unique `actionId`, stable `eventKey`, original `securityId`, `kind`, `status` | Per-unit economic action on that issue, separate from index membership. |
| `quotes` | `securityId`, nonnegative `close`, `basis: unadjusted`, `currency: USD` | `effectiveAt` is the exact valuation timestamp; revisions have separate known clocks. |
| `coverage` | unique `coverageId`, `securityId`, `from`, `throughExclusive`, `domains`, `completeness`, `coverageEvidence` | Full union must cover each holding segment including its endpoint. Complete evidence requires certified provider temporal quality; isolated notices cannot attest it. |
| `observations` | `allowedUse: diagnostic_only` plus observed terms and explicit uncertainty | Raw facts not sufficiently normalized/verified for accounting; never consumed as an action or outcome. |

Coverage domains: `corporate_actions`, `distributions`, `terminal_status`,
`identity`. Coverage's own `knownAt` must precede the evaluation timestamp and
cannot attest beyond its actual source retrieval. An administrative coverage
attestation does not make future action facts visible earlier.

## Action fields

`kind` is `distribution`, `split`, `exchange`, or `zero_recovery`. `status` is
`completed`, `announced`, `unresolved`, or `cancelled`.

- A completed action requires `termsVerified: true`, `settlementEvidence`,
  `settledAt >= effectiveAt`, `knownAt >= settledAt` and
  `entitlementConvention: "effective_at_per_unit_verified"`. `effectiveAt`
  means the documented entitlement/ownership time. Per-unit quantities must
  include evidenced fractional treatment; do not substitute an announced
  ratio for actual completed entitlement terms.
- A split has a strictly positive `ratio` and no deliveries.
- Distribution/exchange deliveries contain positive `perUnit` quantities:
  `{kind: "cash", currency: "USD", perUnit: amount}` or
  `{kind: "asset", securityId: permanentIssueOrRightId, perUnit: quantity}`.
  Distribution retains the original asset; exchange extinguishes it.
- `zero_recovery` requires an empty delivery list and
  `zeroRecoveryConfirmed: true`. This represents an evidenced final
  cancellation without residual rights, not a missing price.
- A cancelled proposal needs `cancelledAt` and `cancellationEvidence`; it
  delivers nothing. Unresolved/announced actions cannot produce cash/shares.
- Use `pitEventId` to explicitly link a terminal action to an existing PIT
  delisting event on the same security. An unresolved PIT terminal observation
  remains binding until corrected in a new PIT dataset, even if a cash-only
  lifecycle record purports to be complete.
- `supersedes` references an earlier action, with the same event key, security
  and effective time, and a strictly later original known clock. Action type
  stays the same except that a terminal zero-recovery/exchange classification
  may be corrected between those two types. Corrections never rewrite an
  earlier evaluation. Competing unsuperseded events or ambiguous simultaneous
  actions fail rather than pick a convenient ordering.

Deliveries add verified units of a different asset, including a contingent
right. A right must itself be redeemed/exchanged or confirmed worthless by the
target, with complete history and identity, before full wealth is available.
The current policy deliberately does not mark unresolved rights to speculative
values. Post-target settlement is an unvalued receivable at the earlier target.

## API and forecasts

```python
pit = PITInputs.load(complete_new_pit_bundle)
cohort = pit.snapshot(origin)  # fails unless the full origin is evidenced
inputs = LifecycleInputs.load(complete_new_lifecycle_bundle)
ledger = inputs.ledger(pit, cohort, target_session_timestamp, evaluation_timestamp)
```

For a separate, explicitly specified experiment, `inputs.evaluate(...)` accepts
the same four arguments plus:

```json
{
  "cohortHash": "hash from the complete frozen cohort",
  "origin": "2020-01-02",
  "targetAt": "2020-12-31T21:00:00Z",
  "rows": [{
    "securityId": "provider issue ID",
    "origin": "2020-01-02",
    "predictedTotalReturnFactor": 1.1,
    "predictedOriginalPriceFactor": 1.05
  }]
}
```

These numbers illustrate the schema only. Supply exactly the entire cohort;
missing/duplicate/replaced securities fail. The two prediction fields are
independent: missing either blocks that metric and triggers no fallback to the
other. Total return includes paid distributions, actual successor holdings and
resolved terminal consideration; original price is only the surviving original
issue's split-adjusted value per initial unit. Existing price-pattern forecasts
and saved research results are not rewritten or re-scored by this module.
