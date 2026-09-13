# E2 quarterly implementation — fixed before the input audit and incremental fit

This implements the original E2 condition: an E1 candidate must qualify on the
earlier selection dates. E1 selected `ridgeAbsolute` on those dates. Its later
uncertainty check failed; it is a research candidate, not a promoted model.

Append six fields to the identical E1 design: quarterly revenue year-over-year
growth, net margin, operating-cash-flow margin, and the preceding-quarter change
in each. Retain Ridge alpha 100, date weighting, training-only imputation and
scaling, folds, labels, and every archived evaluation row. Missing quarterly
fields stay missing and acquire the same training-fitted missing indicators.
Do not tune a model parameter, a threshold, or a feature after seeing E2 results.

Use standard USD US-GAAP tags already named by the annual collector. Extract
60–120 day standalone periods. Derive a quarter from cumulative periods only
with the same concept and fiscal start and 60–120 days between their ends.
Prefer a reported standalone value when both are present. Preserve all source
filings for a difference, including a flag when accessions differ. Match income
and cash flow to the exact revenue period; never divide cumulative income or
cash flow by standalone quarterly revenue. Compare revenue growth only within
the same concept and comparable year-earlier period. Use strictly earlier filed
dates and a maximum latest-quarter age of 200 calendar days.

Before fitting, require the chronology/quarter identity tests to pass, no issuer
identity or source-hash error, and all three base fields on at least 50% of the
archived issuer rows in each of the earlier and later sections. Require at least
20 matched original-release quarters each for NVDA and MSFT, with no unmatched
numeric comparisons among the available matches (tolerance USD 0.5 million for
reported rounding). Missing release/SEC pairs remain explicit, not zero values.
These are engineering eligibility rules, not proof of a certified vintage feed.
Record changed comparative facts, mixed-filing derivations and the limited scope
of the original-release checks. Do not claim every issuer's cash flow was
independently reconciled. A mismatch stops fitting for investigation.

For an eligible data panel, compare the single added-quarterly Ridge model to
the frozen E1 Ridge on equal-date IC, paired date-level differences and the same
5/10/25 bps cohort diagnostics. Keep the candidate only if earlier IC improves.
Report later results even if it fails earlier selection. No automatic promotion.
The second increment (historical valuation) remains blocked until raw prices,
historical share counts and corporate-action bases can actually be reconciled.

The reused historical evaluation is development evidence. A favorable E2 score
cannot retroactively make any previous historical data an untouched holdout.
