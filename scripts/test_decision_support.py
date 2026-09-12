import copy
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from build_decision_support import score,paired_gate,build,change,summarize,capture
from build_market_context import bond_spreads

class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,9,12,tzinfo=timezone.utc)
        self.rows=[dict(date=(self.now-timedelta(days=60-i)).date().isoformat(),close=100+i) for i in range(60)]
        self.r=dict(assetClass='crypto',symbol='X',asOf=self.rows[0]['date'],horizon=30,anchor=100,base=120,low=90,high=140,issuedAt=self.rows[1]['date']+'T02:00:00Z',model='old')
    def test_prospective_date_and_price_errors(self):
        x=score(self.r,self.rows,self.now)
        self.assertEqual(x['targetDate'],self.rows[30]['date'])
        self.assertAlmostEqual(x['mape'],10/130)
        self.assertAlmostEqual(x['baselineMape'],30/130)
        self.assertTrue(x['directionHit'])
    def test_missing_dates_late_issue_and_future(self):
        self.assertEqual(score(self.r,self.rows[:30],self.now)['status'],'pending')
        self.assertEqual(score(self.r,self.rows[:30]+self.rows[31:],self.now)['status'],'unavailable')
        self.assertEqual(score(dict(self.r,issuedAt=self.now.isoformat()),self.rows,self.now)['status'],'excluded')
        self.assertEqual(score(dict(self.r,issuedAt=(self.now+timedelta(days=1)).isoformat()),self.rows,self.now)['status'],'excluded')
        self.assertEqual(score(dict(self.r,anchor=50),self.rows,self.now)['status'],'excluded')
        self.assertIsNone(summarize([dict(self.r,status='pending')])['mape'])
    def test_stock_uses_sessions_crypto_calendar(self):
        hist=[r for r in self.rows if datetime.fromisoformat(r['date']).weekday()<5]
        r=dict(self.r,asOf=hist[0]['date'],anchor=hist[0]['close'],horizon=21,assetClass='stocks')
        self.assertEqual(score(r,hist,self.now)['targetDate'],hist[21]['date'])
    def test_stock_missing_session_does_not_shift_target(self):
        r=dict(self.r,assetClass='stocks',horizon=21)
        calendar=[q['date'] for q in self.rows]
        actual=score(r,self.rows[:8]+self.rows[9:],self.now,calendar)
        self.assertEqual(actual['targetDate'],calendar[21])
        self.assertEqual(score(r,self.rows[:21]+self.rows[22:],self.now,calendar)['status'],'unavailable')
    def test_promotion_pairs_and_nonoverlap(self):
        rows=[]
        for i in range(12):
            origin=datetime(2024,1,1)+timedelta(days=i*40);target=origin+timedelta(days=30)
            for sym in ['A','B','C']:
                for model,error in [('old',.2),('new',.1)]:
                    rows.append(dict(status='scored',model=model,symbol=sym,asOf=origin.date().isoformat(),targetDate=target.date().isoformat(),anchor=100,mape=error,baselineMape=.3))
        self.assertTrue(paired_gate(rows,'old','new')['passed'])
        self.assertFalse(paired_gate(rows[:30],'old','new')['passed'])
        different=copy.deepcopy(rows)
        for r in different:
            if r['model']=='new':r['symbol']='OTHER'
        self.assertEqual(paired_gate(different,'old','new')['pairs'],0)
        overlap=copy.deepcopy(rows)
        for r in overlap:r['targetDate']='2026-01-01'
        self.assertEqual(paired_gate(overlap,'old','new')['dates'],1)
    def test_ledger_is_idempotent_and_never_backdated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'ml').mkdir();(root/'crypto').mkdir();(root/'ml/validation').mkdir()
            data=dict(model='old',generatedAt=self.now.isoformat(),stocks={'A':dict(asOf='2026-09-11',price=100,predictions={'21':dict(forecast=dict(anchor=100,base=110,bear=90,bull=120),validation={})})})
            (root/'ml/latest.json').write_text(json.dumps(data))
            build(root,self.now);paths=list((root/'decision/ledger').glob('*.json'));before=paths[0].read_bytes()
            data['stocks']['A']['predictions']['21']['forecast']['base']=999
            (root/'ml/latest.json').write_text(json.dumps(data));build(root,self.now+timedelta(hours=1))
            self.assertEqual(paths[0].read_bytes(),before)
            self.assertEqual(len(list((root/'decision/ledger').glob('*.json'))),1)
            r=json.loads(before)['records'][0];self.assertEqual(r['issuedAt'],self.now.isoformat())
    def test_changes_report_facts_not_causation(self):
        a=dict(self.r,features={'return30':.1});b=dict(a,asOf='2026-08-01',base=115,features={'return30':.05})
        c=change(b,a);self.assertLess(c['delta'],0);self.assertEqual(len(c['facts']),1)
        self.assertEqual(change(b,None)['status'],'waiting')
    def test_adapters_require_matching_source_and_mature_correction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'ml').mkdir()
            source=dict(model='old',generatedAt=self.now.isoformat(),stocks={'A':dict(asOf='2026-09-11',price=100,predictions={})})
            (root/'ml/latest.json').write_text(json.dumps(source))
            e=dict(asOf='2026-09-11',anchor=100,correction={'targetThrough':'2026-09-10'},variants={'biasCorrected':dict(model='adapter:old:bias',base=105,low=90,high=120,calibration=None,validation={})})
            d=dict(sourceModel='old',sourceGeneratedAt=source['generatedAt'],generatedAt=source['generatedAt'],stocks={'A':{'21':e}})
            path=root/'ml/adaptive.json';path.write_text(json.dumps(d))
            rows,_=capture(root,self.now)
            self.assertEqual(len(rows),1);self.assertIsNone(rows[0]['low']);self.assertFalse(rows[0]['eligible'])
            d['sourceGeneratedAt']='2026-09-10';path.write_text(json.dumps(d))
            self.assertEqual(capture(root,self.now)[0],[])
            d['sourceGeneratedAt']=source['generatedAt'];e['correction']['targetThrough']=e['asOf'];path.write_text(json.dumps(d))
            self.assertEqual(capture(root,self.now)[0],[])
    def test_fed_spread_parsing_and_missing(self):
        rows=bond_spreads('date,gz_spread,ebp,est_prob\n2026-07-01,1.5,-0.3,0.1\n2026-08-01,2.1,0.1,0.2\n',self.now.date())
        self.assertEqual(rows[0]['status'],'ready');self.assertAlmostEqual(rows[0]['change'],.6)
        self.assertEqual(bond_spreads('',self.now.date())[0]['status'],'missing')
        self.assertEqual(bond_spreads('date,gz_spread\n2020-01-01,2',self.now.date())[0]['value'],None)
if __name__=='__main__': unittest.main()
