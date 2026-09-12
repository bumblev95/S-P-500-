import unittest
from collect_simulation_data import valid,merge

class SimulationDataTests(unittest.TestCase):
    def test_impossible_candles_are_rejected(self):
        r=dict(t=0,end=899999,open=100,high=101,low=99,close=100,volume=0)
        self.assertTrue(valid(r))
        for patch in [dict(close=102),dict(low=0),dict(volume=-1),dict(open=float('nan')),dict(end=0)]:
            self.assertFalse(valid(dict(r,**patch)))
    def test_old_bars_are_frozen_and_material_revisions_flagged(self):
        r=dict(t=0,end=899999,open=100,high=101,low=99,close=100,volume=100)
        revised=dict(r,open=50,high=51,low=49,close=50)
        result,changes=merge([r],[revised]);self.assertEqual(result,[r]);self.assertEqual(changes,[0])
        result,changes=merge([r],[dict(r,t=900000,end=1799999)]);self.assertEqual(len(result),2);self.assertEqual(changes,[])

if __name__=='__main__':unittest.main()
