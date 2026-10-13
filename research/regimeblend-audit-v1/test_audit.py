"""Frozen real-cohort replay, rejection, chronology and evidence-boundary checks."""
import copy
import gzip
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import run as audit
import verify


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest,cls.content=audit.read_sources()
        cls.report=json.loads((audit.HERE/'output/results.json').read_text())
        cls.paired=json.loads(gzip.decompress((audit.HERE/'output/paired-predictions.json.gz').read_bytes()))

    def load(self,name):
        return json.loads(self.content['sources/'+name])

    def test_both_original_snapshots_replay_whole_population(self):
        for prefix,summary in [('pr53-','pr53-adaptive-summary.json.gz'),('latest-','latest-summary.json.gz')]:
            with self.subTest(snapshot=prefix):
                replayed=audit.replay(self.load(prefix+'validation-126.json.gz'),
                    self.load(prefix+'adaptive-126.json.gz')['rows'],self.load(summary))
                self.assertEqual(replayed['verification']['fullRows'],3479)
                self.assertEqual(replayed['verification']['finalRows'],1996)
                self.assertTrue(replayed['verification']['predictionBandProvenanceMatch'])
                self.assertTrue(replayed['verification']['comparisonMatch'])

    def test_same_count_and_model_id_are_not_same_evaluation(self):
        c=self.report['snapshotComparison']
        self.assertTrue(c['sameModelID']);self.assertTrue(c['sameSampleSize'])
        self.assertTrue(c['sameProducerBytes']);self.assertTrue(c['sameBaseModelCode'])
        self.assertFalse(c['samePopulation']);self.assertEqual(c['commonExactKeys'],0)
        for row in c['alignment']:
            self.assertEqual(row['commonSymbols'],row['latestN'])
            self.assertEqual(row['changedOriginalPredictions'],row['latestN'])
            self.assertEqual(row['changedOutcomes'],row['latestN'])
            self.assertEqual(row['changedTargetDates'],row['latestN'])

    def test_bad_latest_candidate_is_diagnostic_only_and_none_selected(self):
        self.assertEqual(self.report['snapshots']['pr53']['legacyComparison']['chosen'],'biasCorrected')
        self.assertEqual(self.report['snapshots']['latest']['legacyComparison']['chosen'],'regimeBlend')
        for snapshot in self.report['snapshots'].values():
            c=snapshot['guardedComparison']
            self.assertIsNone(c['selectedCandidate']);self.assertFalse(c['selectionEligible'])
            self.assertEqual(c['chosenScope'],'diagnostic-only');self.assertFalse(c['passed'])
            self.assertFalse(c['productionEligible']);self.assertFalse(c['pitComplete'])

    def test_real_later_labels_cannot_change_selection(self):
        rows=self.load('latest-adaptive-126.json.gz')['rows'];a=audit.guarded.compare(rows)
        changed=copy.deepcopy(rows)
        for row in changed:
            if row['origin'] >= a['evaluationStart']:
                row['y']=1.;row['regimeBlend']=1.;row['biasCorrected']=1.
        b=audit.guarded.compare(changed)
        for field in ('selectedCandidate','diagnosticChoice','selectionEvaluation','selectionChecks'):
            self.assertEqual(a[field],b[field])

    def test_real_future_outcomes_cannot_change_pooled_or_local_fit(self):
        rows=audit.guarded.normalize(self.load('latest-validation-126.json.gz'))
        origin='2024-10-04';changed=copy.deepcopy(rows)
        for row in changed:
            if row['targetDate'] >= origin:row['y']=9.
        for regime in (None,'above200HighVol','above200LowVol','below200HighVol','below200LowVol'):
            a=rows if regime is None else [r for r in rows if audit.legacy.regime(r)==regime]
            b=changed if regime is None else [r for r in changed if audit.legacy.regime(r)==regime]
            self.assertEqual(audit.legacy.fit(a,origin),audit.guarded.fit(b,origin))

    def test_all_fit_clocks_are_strictly_prior(self):
        for snapshot in self.report['snapshots'].values():
            c=snapshot['legacyComparison'];self.assertLess(c['selectionTargetThrough'],c['evaluationStart'])
            for fold in snapshot['clocks']:
                self.assertLess(fold['targetThrough'],fold['origin'])
                for target in fold['localTargetThrough'].values():self.assertLess(target,fold['origin'])
            for origin,regime in snapshot['macroRegimes'].items():self.assertLess(regime['through'],origin)

    def test_additive_decomposition_and_direction_transitions(self):
        for snapshot in self.report['snapshots'].values():
            total=snapshot['pairedChanges']['all']
            for values in snapshot['contributions'].values():
                self.assertAlmostEqual(sum(values.values()),total['returnMaeChange'],places=14)
            self.assertAlmostEqual(total['weightedWrongToCorrect']-total['weightedCorrectToWrong'],total['directionChange'],places=14)
        latest=self.report['snapshots']['latest']['pairedChanges']['all']
        self.assertEqual(latest['directionFlips'],1160)
        self.assertEqual(latest['correctToWrong'],310);self.assertEqual(latest['wrongToCorrect'],206)

    def test_every_output_row_keeps_all_frozen_price_predictions(self):
        for snapshot,prefix in [('pr53','pr53-'),('latest','latest-')]:
            saved={(r['symbol'],r['origin']):r for r in self.load(prefix+'adaptive-126.json.gz')['rows']}
            for row in self.paired[snapshot]:
                reference=saved[(row['symbol'],row['origin'])]
                for name in ('y','targetDate',*audit.METHODS):self.assertEqual(row[name],reference[name])
            self.assertEqual(len(self.paired[snapshot]),1996)

    def test_pit_lifecycle_and_live_state_stay_blocked(self):
        ready=self.report['sourceIntegrityVsReadiness'];self.assertEqual(ready['pitReady'],0)
        self.assertEqual(ready['pitOrigins'],34);self.assertEqual(ready['lifecycleReady'],0)
        self.assertFalse(ready['modelTrainingAllowed']);self.assertFalse(ready['productionChangesAllowed'])
        self.assertFalse(self.report['productionEligible']);self.assertTrue(self.report['notNewHoldout'])
        boundary=self.report['productionBoundary'];self.assertEqual(boundary['promotionEvents'],0)
        self.assertFalse(boundary['usedForTrading']);self.assertFalse(boundary['liveForecastChanged'])
        self.assertEqual(self.report['independentEvaluationDates'],4)

    def test_252_has_five_source_folds_but_no_adapter_validation(self):
        h=self.report['horizon252'];self.assertEqual(h['sourceDates'],5)
        self.assertEqual(h['adapterRows'],0);self.assertEqual(h['status'],'insufficient')
        self.assertEqual(max(h['maturedPriorDatesByOrigin'].values()),3)
        self.assertEqual(h['requiredMaturedPriorDates'],4)

    def test_saved_source_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);shutil.copy2(audit.HERE/'input-manifest.json',folder)
            for entry in self.manifest['files']:
                dest=folder/entry['file'];dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(audit.HERE/entry['file'],dest)
            target=folder/'reuse/build_adaptive_research.py';target.write_bytes(target.read_bytes()+b'\n# changed')
            with self.assertRaisesRegex(ValueError,'hash mismatch'):audit.read_sources(folder)

    def test_unsafe_output_never_addresses_operating_files(self):
        with self.assertRaisesRegex(ValueError,'isolated experiment'):audit.run(audit.ROOT/'ml')
        with self.assertRaisesRegex(ValueError,'isolated experiment'):audit.run(audit.HERE)

    def test_all_preserved_baseline_files_and_output_hashes(self):
        self.assertEqual(verify.verify_preserved(),1495)
        self.assertEqual(len(verify.verify_output()),3)


if __name__ == '__main__':unittest.main()
