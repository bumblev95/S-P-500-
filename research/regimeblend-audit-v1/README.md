# Frozen regimeBlend audit

Start with [FINDINGS.md](FINDINGS.md). This is an offline, quarantined retrospective audit of the October 13 snapshot and PR #53's fixed results. No candidate is promoted. PR #25's PIT and lifecycle readiness remain 0/34; no new historical universe or real lifecycle outcomes are supplied.

`input-manifest.json` pins 25 saved inputs with stored/raw SHA256, paths and commits. The source-model metadata file is explicitly a projection excluding stocks; its original file hash is preserved. All other saved inputs preserve complete source bytes. `reuse/` contains exact historical producers for replay and code comparison, including the former operating/visual boundaries; no original HGB is retrained. Running the saved code means replaying existing adapter fitting on already examined outcomes, not obtaining new evidence.

The verified main baseline is `632dfa1e0e616544ec6fcfb0a1854971a22696f5`, PR #53 head is `9c82f01d86dae0c7541211ad082f352417319f2d`, and PR #25 head is `1aa16f7a831b0aeed411593fe64464af94115cd5`. The PR #53 bundle itself froze main at `9e07f96df6b43689bb75dcc005329964db33e882`.

From the repository root, using Python 3.12 and Node 22:

```bash
python -m pip install -r research/regimeblend-audit-v1/requirements.txt
python -m unittest discover -s scripts -p test_adaptive_research.py
python -m unittest discover -s scripts -p test_decision_support.py
python -m unittest discover -s scripts -p test_regimeblend_guards.py
python -m unittest discover -s research/regimeblend-audit-v1 -p test_audit.py
node scripts/test_decision_support.cjs
node scripts/test_regimeblend_ui.cjs
python research/regimeblend-audit-v1/run.py --output research/regimeblend-audit-v1/replay-a
python research/regimeblend-audit-v1/run.py --output research/regimeblend-audit-v1/replay-b
python research/regimeblend-audit-v1/verify.py --output research/regimeblend-audit-v1/replay-a --compare research/regimeblend-audit-v1/replay-b
```

Do not execute the ordinary production builders for this audit. The audit accepts only output directories inside this experiment and never writes operating forecasts, prices, ranking, registry, ledger, or model artifacts. `verify.py` checks all 1,495 preserved baseline files and output hashes. Two executions within one environment must be byte-identical; frozen original predictions, bands and metrics replay within 1e-14. Python version is recorded, so byte identity across different Python/NumPy builds is not claimed.

`output/results.json` contains both complete snapshot comparisons, legacy versus guarded selection, subgroup metrics, component diagnostics, chronology and remaining evidence gaps. `output/paired-predictions.json.gz` contains every final evaluation row, preserving all five original price methods and explicitly separating component diagnostics. `output/metrics.csv` provides exact comparable tables. Group metrics condition the whole-cohort date-equal weights rather than rebuilding weights within each group; contributions sum to the full change.

The proposed changes outside this directory are limited to:

- Research selection: require joint feasibility before qualifying any candidate; preserve legacy `chosen` for existing display consumers, with `chosenScope=diagnostic-only` and `selectedCandidate=null` when no candidate qualifies. Later outcomes cannot reselect. All statistical success remains production ineligible.
- Operating input boundary: quarantine the `completed-error-adapter-v1:` namespace at the existing registry gate. A perfect prospective price screen or forged eligible/passed flag cannot release it. An already contaminated registry stops before writes. Existing non-adapter numerical promotion conditions are unchanged.
- Display/chart boundary: label diagnostic candidates and new failed checks correctly; refuse this namespace when applying a promoted chart default. No chart price is changed on existing snapshots.
- Read-only, unscheduled regression CI and tests. Existing deployment workflows, TOP3, trading rules, source model/adapter numeric fitting, and shadow runtime are unchanged.

Releasing the quarantine would require a separate reviewed evidence/protocol change after PIT, permanent identity, vintage and lifecycle blockers close. This Draft does not close those gaps and must not be auto-merged.
