# EOD publication and follow-up research

The weekday `30 23 * * 1-5` schedule and the price/forecast/ranking calculations
are unchanged. GitHub may delay scheduled starts; this change removes research
from the publication dependency, rather than guaranteeing an exact wall-clock
update time.

`Update S&P 500 EOD prices` downloads prices and runs `build_forecasts.py`, then
publishes **one commit** containing only `prices/latest_prices.csv`,
`forecasts/latest.json` and the immutable `forecasts/archive` records. It uses
the existing requested ticker policy, with no fixed count that could silently
accept a missing ticker after membership changes. The present public universe
has 505 rows, including its benchmark symbols.

Before staging any files, the gate checks the exact requested symbol set,
duplicates, finite positive closes, the latest completed XNYS session with the
collector's existing 15-minute close buffer, and one download timestamp.
The requested universe must also contain at least as many symbols as the
previous public CSV; a truncated constituent/watchlist input cannot silently
publish a smaller, internally consistent subset.
Retained rows from failed individual downloads are rejected even when the row
count is unchanged. Every forecast and both the full downloaded history and
published chart must agree with its CSV date, timestamp and six-decimal close.
The gate also rejects a provider snapshot whose dates are uniformly outdated.
All partial/failing cases leave the previous public Git commit intact. The
generated files remain local to the failed runner; no per-file public writes,
invented padding, ranking changes or automatic threshold changes are used.

When Yahoo supplies the required completed US equity daily bar but its Close
is null, the collector may recover that **one bar** from Nasdaq's public
historical endpoint. This is not a last-quote or after-hours substitution.
The response must identify the same symbol and date; its preceding three daily
closes must match Yahoo at cent precision, with the nearest anchor on the
previous XNYS session. Its current Open/High/Low must also match the supplied
Yahoo values at cent precision. The bar must have finite positive, consistent
OHLC and volume. Cent comparison reflects displayed provider precision and
does not alter any forecast, ranking, signal or research threshold.

The Nasdaq daily OHLCV replaces the incomplete bar together; older Yahoo
history remains intact. No missing history or missing latest-date bar is
synthesized. USD, equity and New York timezone identity are required. Only
one secondary request is made for an eligible missing bar; errors or mismatches
leave the original history untouched and the all-symbol publication gate still
blocks the run. Authentication/throttling responses stop further collection;
there are no alternate-host or credential workarounds.

The collector stores the original secondary response, SHA-256, URL, retrieval
timestamp and original Yahoo OHLC in the history's `eodRecovery` and a
base64-encoded `eodProvenance` final CSV column. Normal Yahoo rows leave that
column empty. The publication gate rechecks the evidence and its exact OHLCV
against the CSV, full history and public forecast chart before the single
commit. `source` identifies the recovered row in CSV and forecasts. The exact
history/evidence is also transferred to research in the existing input artifact.

The fast workflow retains its name so the existing homepage `workflow_run`
callback starts as soon as it completes. This is required because a push with
the built-in `GITHUB_TOKEN` does not trigger the normal homepage `push` callback.
The homepage already publishes rankings before its news translation work.

The fast run transfers a 14-day Actions artifact, `eod-research-inputs`, with
its published commit SHA, request receipt, SHA-256 hashes of public inputs and
every full downloaded history, and the histories themselves. The follow-up
`Update S&P 500 EOD forecast research` restores that commit and checks every
hash before running the original learned/audit/stability/comparison/adaptive/
live-score commands in their original order. It neither downloads prices again
nor substitutes the 253-bar public charts for the full training histories.
Research is committed separately under `ml` only.

Research shares the `decision-support` concurrency group with the other
adaptive-output writer, independent of the fast publisher's `market-data`
group. The decision workflow's EOD callback follows research completion so it
continues to consume finished learned/adaptive results. A new public snapshot
supersedes unfinished older research: its results are retained in the
`eod-research-results` artifact and cannot replace current `ml` outputs. Input
changes during a rebase or a rejected non-fast-forward push fail safely; no
force pushes are used. A research error cannot undo the earlier public commit.

To retry research without a duplicate EOD download, dispatch the research
workflow with the successful fast run's `source_run_id` while its input artifact
is retained. Missing, incomplete or changed artifacts fail verification.

Validation: `python -m unittest discover -s scripts -p 'test_eod_*.py'`.
These tests use synthetic prices and local bare Git repositories to verify
505-row atomic publication, failed-collector retained rows, missing/duplicate/
stale/mismatched values, holidays/early closes/DST, unchanged first-issued
forecast rules, full-history transfer integrity, concurrent unrelated commits,
separate research commits and protection against superseded research. The CI
workflow also runs the existing forecast, homepage TOP3 and entry-indicator
regressions. No production prices or research outcomes are synthesized by tests.
