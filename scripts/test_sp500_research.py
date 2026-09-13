import json, math, tempfile, unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta, date
from unittest.mock import patch
from urllib.error import HTTPError
import numpy as np
import build_research_inputs as sec
import build_environment_research as model
from test_sec_import import payload

class FullUniverse(unittest.TestCase):
    def root(self,tmp,members):
        root=Path(tmp);(root/'research').mkdir()
        (root/'research/universe.json').write_text(json.dumps({'members':{s:{'cik':c} for s,c in members.items()}}))
        return root
    def test_share_classes_download_once_and_reuse_fresh_history(self):
        now=datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root=self.root(tmp,{'GOOG':1652044,'GOOGL':1652044})
            with patch.object(sec,'request',return_value=payload(1652044)) as request,patch.object(sec,'sec_identity'),patch.object(sec.time,'sleep'):
                out=sec.collect_sec({},root,True,now)
                self.assertEqual(request.call_count,1)
                self.assertEqual(out['secCoverage']['usableIssuers'],1)
                self.assertEqual(out['secCoverage']['usableTickers'],2)
                again=sec.collect_sec(out,root,True,now+timedelta(hours=1))
                self.assertEqual(request.call_count,1)
                self.assertEqual(again['stocks']['GOOG']['retrievedAt'],out['stocks']['GOOG']['retrievedAt'])
    def test_denial_stops_next_issuer_and_persists_cooldown(self):
        now=datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root=self.root(tmp,{'A':1,'B':2})
            with patch.object(sec,'request',side_effect=HTTPError('https://data.sec.gov',403,'Forbidden',{},None)) as request,patch.object(sec,'sec_identity'),patch.object(sec.time,'sleep'):
                out=sec.collect_sec({},root,True,now)
                self.assertEqual(request.call_count,1)
                self.assertGreater(out['secBlockedUntil'],now.isoformat())
                self.assertEqual(json.loads((root/'research/inputs.json').read_text())['secBlockedUntil'],out['secBlockedUntil'])
                sec.collect_sec(out,root,True,now+timedelta(minutes=1))
                self.assertEqual(request.call_count,1)
    def test_issuer_mismatch_never_becomes_training_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=self.root(tmp,{'A':1})
            with patch.object(sec,'request',return_value=payload(2)),patch.object(sec,'sec_identity'),patch.object(sec.time,'sleep'):
                out=sec.collect_sec({},root,True,datetime.now(timezone.utc))
            self.assertEqual(out['secCoverage']['usableIssuers'],0)
            self.assertIn('identity mismatch',out['errors'][0])
    def test_vector_features_keep_the_original_price_windows(self):
        prices=np.exp(np.cumsum(np.random.default_rng(23).normal(0,.01,400)))
        rows=[{'date':str(date(2020,1,1)+timedelta(days=i)),'close':v} for i,v in enumerate(prices)]
        actual=model.features(rows);ret=np.diff(np.log(prices))
        for i in (199,230,399):
            a=prices[i-199:i+1];r=ret[i-90:i]
            expected=[np.log(prices[i]/prices[i-n]) for n in (7,30,90,180)]
            expected += [np.std(r[-n:],ddof=1)*np.sqrt(252) for n in (30,90)]
            expected += [prices[i]/a[-n:].mean()-1 for n in (20,50,200)]
            expected += [prices[i]/a[-90:].max()-1]
            np.testing.assert_allclose(actual[rows[i]['date']],expected,rtol=1e-12,atol=1e-12)
    def test_one_issuer_one_training_sample_but_both_share_predictions(self):
        prices=[dict(date=str(date(2020,1,1)+timedelta(days=i)),close=100+i/10) for i in range(300)]
        f=model.features(prices);context={s:dict(features=f,dates=np.array(sorted(f))) for s in model.PROXIES}
        rows,latest=model.records({'GOOG':prices,'GOOGL':prices},context,21,'stocks',{'symbolCIKs':{'GOOG':1,'GOOGL':1}})
        self.assertEqual({r['symbol'] for r in rows},{'GOOG'})
        self.assertEqual(set(latest),{'GOOG','GOOGL'})
        self.assertEqual(latest['GOOG']['origin'],prices[-1]['date'])
    def test_down_recall_and_sector_comparisons_share_rows(self):
        rows=[dict(symbol='A',origin='2020-01-01',y=.8,noChange=1.,balanced=1.1,availabilityControl=1.,enriched=.9),
              dict(symbol='B',origin='2020-01-01',y=1.3,noChange=1.,balanced=1.1,availabilityControl=1.,enriched=1.2)]
        result=model.grouped_comparison(rows,{'A':'Finance','B':'Tech'})
        self.assertEqual(result['Finance']['metrics']['enriched']['downRecall'],1.)
        self.assertEqual(result['Finance']['metrics']['balanced']['downRecall'],0.)
        self.assertEqual(result['Tech']['metrics']['balanced']['n'],result['Tech']['metrics']['enriched']['n'])

if __name__=='__main__':unittest.main()
