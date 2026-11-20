import copy
import unittest
from research_hybrid_candidates import candidates
from build_environment_research import direction_label, score

class HybridResearchTests(unittest.TestCase):
    def test_fixed_values_and_sec_veto(self):
        row=dict(priceOnly=1.10,horizonModel=.95,secDynamicsDirection=-1)
        self.assertAlmostEqual(candidates(row)['anchor_force'],.975)
        self.assertAlmostEqual(candidates(row)['price_force'],1.025)
        self.assertEqual(candidates(row)['sec_agreement'],.95)
        row['secDynamicsDirection']=1
        self.assertAlmostEqual(candidates(row)['sec_agreement'],1.05)

    def test_ignores_future_outcome_and_has_coherent_direction(self):
        row=dict(priceOnly=1.05,horizonModel=.96,secDynamicsDirection=-1,y=.5,targetDate='2099-01-01')
        a=candidates(row); altered=copy.deepcopy(row); altered['y']=4.; altered['targetDate']='2100-01-01'
        self.assertEqual(a,candidates(altered))
        self.assertEqual(direction_label(a['sec_agreement']),-1)
        result=score([dict(origin='2020-01-01',y=.9,**a)],'sec_agreement')
        self.assertEqual(result['directionAccuracy'],result['returnDirectionAccuracy'])
        self.assertEqual(result['downRecall'],1.)

if __name__ == '__main__': unittest.main()
