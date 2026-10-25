"""Cohort, time-boundary, joint-risk, source integrity and replay regressions."""
import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from threadpoolctl import threadpool_limits
import run as study

class ResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest,cls.content=study.read_sources()
        cls.source=json.loads(cls.content['sources/validation-126.json.gz'])
        cls.rows=study.adapter.normalize(cls.source)
        cls.stored=json.loads(cls.content['sources/adaptive-126.json.gz'])['rows']
        cls.summary=json.loads(cls.content['sources/adaptive-summary.json.gz'])
        cls.protocol=json.loads((study.HERE/'PROTOCOL.json').read_text())
        cls.report=json.loads((study.HERE/'output/results.json').read_text())
        cls.predictions=json.loads(gzip.decompress((study.HERE/'output/predictions.json.gz').read_bytes()))

    def test_exact_cohort_no_model_specific_omissions(self):
        expected={(r['symbol'],r['origin']) for r in self.stored if r['origin']>='2024-10-03'}
        actual={(r['symbol'],r['origin']) for r in self.predictions}
        self.assertEqual(expected,actual)
        self.assertEqual(len(actual),1996)
        self.assertTrue(all(set(r['methods'])==set(study.PRICE+study.DIRECTION) for r in self.predictions))

    def test_replay_existing_predictions_and_checks(self):
        _,result=study.original_adapter_replay(self.source,self.stored,self.summary)
        self.assertTrue(result['comparisonMatchWithinTolerance'])
        self.assertEqual(result['comparison']['checks'],self.summary['horizons']['126']['comparison']['checks'])

    def test_duplicate_cohort_fails(self):
        with self.assertRaises(ValueError):study.validate(self.rows+[self.rows[0]],self.source)

    def test_missing_feature_fails_whole_cohort(self):
        rows=copy.deepcopy(self.rows);rows[0]['ma200']=float('nan')
        with self.assertRaises(ValueError):study.validate(rows,self.source)

    def test_overlapping_date_block_fails(self):
        rows=copy.deepcopy(self.rows);rows[0]['targetDate']='2021-04-02'
        with self.assertRaises(ValueError):study.validate(rows,self.source)

    def test_source_clock_fails(self):
        source=copy.deepcopy(self.source);source['folds'][0]['trainTargetThrough']=source['folds'][0]['origin']
        with self.assertRaises(ValueError):study.validate(self.rows,source)

    def test_source_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);(folder/'input-manifest.json').write_text(json.dumps(self.manifest))
            for entry in self.manifest['files']:
                p=folder/entry['file'];p.parent.mkdir(parents=True,exist_ok=True)
                p.write_bytes((study.HERE/entry['file']).read_bytes())
            p=folder/self.manifest['files'][0]['file'];p.write_bytes(p.read_bytes()+b'corrupt')
            with patch.object(study,'HERE',folder):
                with self.assertRaises((ValueError,EOFError,gzip.BadGzipFile)):study.read_sources()

    def test_split_clock_and_no_future_outcome_effect(self):
        origin='2024-10-03';test=[r for r in self.stored if r['origin']==origin]
        changed=copy.deepcopy(self.rows)
        for r in changed:
            if r['targetDate']>=origin:r['y']=9.
        with threadpool_limits(limits=2):
            first,_,clock=study.classifiers(self.rows,test,self.protocol)
            second,_,_=study.classifiers(changed,test,self.protocol)
        for name in first:np.testing.assert_array_equal(first[name],second[name])
        self.assertLess(clock['fitTargetThrough'],clock['calibrationDates'][0])
        self.assertLess(clock['calibrationTargetThrough'],origin)

    def test_blend_selection_no_future_outcome_effect(self):
        changed=copy.deepcopy(self.rows)
        for r in changed:
            if r['targetDate']>='2024-10-03':r['y']=9.
        self.assertEqual(study.choose_blends(self.rows,'2024-10-03',self.protocol),
                         study.choose_blends(changed,'2024-10-03',self.protocol))

    def test_classifier_numeric_price_unchanged(self):
        for r in self.predictions:
            for name in study.DIRECTION:self.assertEqual(r['methods'][name]['ratio'],r['methods']['original']['ratio'])

    def test_recall_gain_cannot_override_false_warning_guard(self):
        original=self.report['scores']['all']['original'];candidate=copy.deepcopy(original)
        candidate.update(downRecall=.9,downPrecision=.9,downWarnings=300,
            downFalsePositiveRate=.01,directionAccuracy=.9,balancedAccuracy=.9,upRecall=.9)
        self.assertFalse(study.joint_checks(candidate,original,self.protocol)['falseDownNotWorse'])

    def test_pit_and_revisited_data_always_block_promotion(self):
        self.assertIsNone(self.report['selectedCandidate'])
        for candidate in self.report['gates'].values():
            self.assertFalse(candidate['eligible']);self.assertFalse(candidate['passed'])
            self.assertFalse(candidate['checks']['pitComplete'])
            self.assertFalse(candidate['checks']['untouchedProspectiveEvidence'])

    def test_error_decomposition_adds_to_total(self):
        total=self.report['paired']['all']['returnMaeChange']
        for values in self.report['contributions'].values():self.assertAlmostEqual(sum(values.values()),total,places=14)

    def test_direction_transition_accounting(self):
        p=self.report['paired']['all'];self.assertEqual(p['directionFlips'],75)
        self.assertEqual(p['correctToWrong'],39);self.assertEqual(p['wrongToCorrect'],4)

    def test_macro_uses_prior_session_only(self):
        for origin,regime in self.report['macroRegimes'].items():self.assertLess(regime['through'],origin)

    def test_unsafe_output_path_rejected(self):
        with self.assertRaises(ValueError):study.run(study.HERE.parent/'outside')

if __name__=='__main__':unittest.main()
