import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from build_forecast_comparison import compare

class ComparisonTests(unittest.TestCase):
    def test_current_target_never_selects_current_model(self):
        rows=[dict(origin=f'202{i}-01-01',targetDate=f'202{i}-06-01',symbol='TEST',y=.1,pred=.1,trend=.03) for i in range(1,6)]
        a=compare(rows)
        self.assertTrue(a['choices'])
        for c in a['choices']:self.assertLess(c['selectionTargetThrough'],c['origin'])
        rows[-1]['y']=-.8
        b=compare(rows)
        self.assertEqual(a['choices'][-1]['chosen'],b['choices'][-1]['chosen'])
        self.assertNotEqual(a['selector']['mae'],b['selector']['mae'])
        self.assertTrue(all(q['n']==b['selector']['n'] for q in b['laterDates'].values()))

    def test_unmatured_labels_and_empty(self):
        rows=[dict(origin='2021-01-01',targetDate='2029-01-01',symbol='TEST',y=.1,pred=.1,trend=.03)]
        self.assertEqual(compare(rows)['selector']['n'],0)
        self.assertEqual(compare([])['selector']['n'],0)

if __name__=='__main__':unittest.main()
