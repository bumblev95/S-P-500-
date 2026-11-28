# Prospective observation audit results

This audit pairs predictions that were immutably issued before the outcome with the fixed close on their 21st XNYS session. The audit protocol itself is post-target and the common comparison has one issue date, so no method is promotable.

## Result

- Common cohort: 15 stocks, one issue date, zero abstentions.
- Full v4/v5 cohort: 493/501 fixed-source targets; aggregate metrics blocked because eight outcomes are absent.
- Long horizons: 13,514 issued 126-session rows and 14,564 issued 252-session rows; zero matured or scored here.
- Best common-cohort magnitude result: v5 horizon model, 4.55% price MAPE and 4.84 percentage-point return MAE, versus 5.10% and 5.46 pp for no change.
- Direction tradeoff: the v5 numeric sign and stored `chosen` called every stock neutral, while raw-score argmax called every stock up; neither detected a decline. The separately issued simple trend had 33.33% up recall, 33.33% down recall and 55.56% balanced direction accuracy, but higher magnitude errors and one false down warning.
- Both registered hypotheses fail. No blend is evaluated after observing the target, no candidate is selected, and no production file is changed.

Exact row-level results, separately scored numeric-sign/raw-argmax/stored-chosen directions, probability diagnostics, input hashes and readiness counts are in `results.json`. Two independent replays produced SHA-256 `571e1d90273b7db1b63133d8930b28935e618745dc8ec0e1c455b43b3888abd7`.
