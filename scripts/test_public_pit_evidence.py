"""Real-data evidence checks and fail-closed regressions; never fit a model."""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from audit_public_pit_evidence import FOLDER, ROOT, normalize, read, run, freeze, verify_lock
from pit_sp500_inputs import InputBlocked, InputError, PITInputs, session_open, timestamp
from research_merger_lifecycle import LifecycleInputs

class PublicEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pit=PITInputs.load(FOLDER)
        cls.report=run(verify=True)
        cls.members=read(FOLDER,'membership-observations.json')['observations']

    def test_all_34_origins_remain_blocked(self):
        self.assertEqual((self.report['originCount'],self.report['readyOriginCount']), (34,0))
        for r in self.report['origins']:
            with self.assertRaises(InputBlocked):self.pit.snapshot(r['origin'])

    def test_priority_windows_are_supported_but_not_full_universes(self):
        for d in ['2025-02-07','2025-04-25']:
            row=next(r for r in self.report['origins'] if r['origin']==d)
            self.assertEqual(row['candidateWindowComparisonCounts'],dict(match=8,conflict=0,unconfirmed=0))
            self.assertFalse(row['ready'])
        self.assertEqual(self.pit.data['baselines'],[])
        self.assertEqual(self.pit.data['coverage'],[])

    def test_candidate_partitions_retain_all_rows(self):
        partitions=self.report['candidateComparisonPartitions']
        ids=[r['candidateId'] for rows in partitions.values() for r in rows]
        self.assertEqual(len(ids),1534);self.assertEqual(len(set(ids)),1534)
        self.assertEqual(self.report['candidateComparisonCounts'],dict(match=68,conflict=2,unconfirmed=1464))
        self.assertTrue(all(r['securityId'] is None and r['historicalKnownAt'] is None for rows in partitions.values() for r in rows))

    def test_conflicts_are_not_repaired_or_counted_as_matches(self):
        rows=self.report['candidateComparisonPartitions']['conflict']
        self.assertEqual({r['ticker'] for r in rows},{'VFC','XRAY'})
        self.assertEqual({r['date'] for r in rows},{'2024-04-01','2024-04-02'})
        self.assertTrue(all(r['conflictingOfficialEventIds'] and not r['matchedOfficialEventIds'] for r in rows))

    def test_solv_sector_footnote_has_two_effective_clocks(self):
        sid=next(r['securityId'] for r in self.members if r['ticker']=='SOLV')
        for d,name in [('2024-04-01','Industrials'),('2024-04-02','Industrials'),('2024-04-03','Health Care')]:
            events=self.pit.visible_events(session_open(d))
            self.assertEqual(self.pit._latest(events,sid,'sector')['value']['name'],name)
        self.assertTrue(all(e['knownAt']=='2024-03-28T04:00:00+00:00' for e in self.pit.events.values() if e['securityId']==sid))

    def test_membership_announcement_is_not_effective_membership(self):
        sid=next(r['securityId'] for r in self.members if r['ticker']=='DASH')
        self.assertFalse(any(e['securityId']==sid for e in self.pit.visible_events(session_open('2025-03-10'))))
        self.assertTrue(any(e['securityId']==sid for e in self.pit.visible_events(session_open('2025-03-24'))))

    def test_november_changes_do_not_enter_october_31_origin(self):
        sid=next(r['securityId'] for r in self.members if r['ticker']=='Q')
        self.assertFalse(any(e['securityId']==sid for e in self.pit.visible_events(session_open('2025-10-31'))))

    def test_dfs_terms_not_backdated_to_closing(self):
        e=self.pit.events['public-dfs-terminal']
        self.assertEqual(e['knownAt'],'2025-05-20T04:00:00+00:00')
        self.assertEqual(timestamp(e['effectiveAt']).date().isoformat(),'2025-05-19') # end of May 18 EDT in UTC
        self.assertNotIn(e,self.pit.visible_events(session_open('2025-05-19')))
        self.assertEqual(e['value']['settlementStatus'],'unresolved')

    def test_dfs_alias_retirement_is_not_successor_price_splicing(self):
        e=self.pit.events['public-dfs-alias-retired']
        self.assertIsNone(e['value']['symbol']);self.assertEqual(e['value']['venue'],'NYSE')
        self.assertFalse(self.pit.data['prices']);self.assertFalse(self.pit.data['outcomes'])

    def test_lifecycle_terms_do_not_create_completed_actions(self):
        lc=LifecycleInputs.load(FOLDER)
        self.assertFalse(lc.assets);self.assertFalse(lc.actions);self.assertFalse(lc.data['quotes']);self.assertFalse(lc.data['coverage'])
        self.assertTrue(all(r['totalReturnFactor'] is None for r in lc.data['observations']))
        self.assertEqual(self.report['lifecycleReadyOriginCount'],0)

    def test_paramount_elections_remain_unresolved(self):
        row=next(r for r in read(FOLDER,'lifecycle-inputs.json')['observations'] if r.get('observationId')=='paramount-elections')
        self.assertEqual(row['classBCashProrationStated'],0.60925910)
        self.assertEqual(row['status'],'unresolved')
        self.assertFalse(any(r['ticker'] in ['PARA','PSKY'] for r in self.members))
        unmatched=self.report['candidateComparisonPartitions']['unconfirmed']
        self.assertTrue(any(r['ticker']=='PARA' and r['date']=='2025-08-08' for r in unmatched))
        self.assertTrue(any(r['ticker']=='PSKY' and r['date']=='2025-08-08' for r in unmatched))

    def test_cik_class_is_not_a_permanent_security_id(self):
        rows=read(FOLDER,'identity-observations.json')['observations']
        self.assertTrue(all(r['permanentSecurityId'] is None and not r['identityVerifiedForPIT'] for r in rows))
        self.assertFalse(any(e['kind']=='identity' for e in self.pit.events.values()))
        self.assertTrue(all(s['provisional'] for s in self.pit.securities.values()))

    def test_coinbase_report_period_is_not_availability(self):
        s=self.pit.sources['coin-20250213-cover']
        self.assertEqual(s['publicationDate'],'2025-02-13')
        self.assertEqual(s['availabilityFloor'],'2025-02-14T05:00:00+00:00')

    def test_gics_proposal_does_not_assign_final_company_sectors(self):
        self.assertFalse(self.report['finalCompanyGICS2023MapAcquired'])
        self.assertFalse(any(e['sourceId'].startswith('gics-') for e in self.pit.events.values()))

    def test_capture_failure_is_not_a_fact_or_zero_recovery(self):
        self.assertEqual(self.report['failedCaptureIds'],['fdic-20230312'])
        self.assertNotIn('fdic-20230312',self.pit.sources)
        lc=LifecycleInputs.load(FOLDER)
        self.assertFalse(any(r.get('kind')=='zero_recovery' for r in lc.data['actions']))

    def test_extracts_do_not_claim_original_http_or_archival_vintage(self):
        lock=read(FOLDER,'source-lock.json')
        self.assertTrue(all(not r['originalHTTPPayloadAvailable'] and not r['historicalRevisionVintageCertified'] for r in lock['newCaptures']))
        self.assertTrue(all(s['temporalQuality']=='dated_notice' for s in self.pit.sources.values() if s['sourceId']!='current-universe'))

    def test_payload_tampering_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'bundle';shutil.copytree(FOLDER,folder)
            with (folder/'sources/sp-20250307.web.json').open('ab') as f:f.write(b' ')
            with self.assertRaises(InputError):normalize(folder)

    def test_unsupported_normalization_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'bundle';shutil.copytree(FOLDER,folder)
            spec=read(folder,'membership-observations.json');spec['observations'][0]['sectorLabel']='Invented sector'
            (folder/'membership-observations.json').write_text(json.dumps(spec))
            with self.assertRaises(InputError):normalize(folder)

    def test_invented_effective_date_and_venue_fail(self):
        for field,value in [('effectiveDate','2010-01-01'),('venue','INVENTED')]:
            with tempfile.TemporaryDirectory() as tmp:
                folder=Path(tmp)/'bundle';shutil.copytree(FOLDER,folder)
                spec=read(folder,'membership-observations.json');spec['observations'][0][field]=value
                (folder/'membership-observations.json').write_text(json.dumps(spec))
                with self.assertRaises(InputError):normalize(folder)

    def test_freeze_preflight_prevents_partial_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            a,b=Path(tmp)/'a',Path(tmp)/'b';b.write_bytes(b'old')
            with self.assertRaises(InputError):freeze({a:b'new',b:b'different'})
            self.assertFalse(a.exists());self.assertEqual(b.read_bytes(),b'old')

    def test_cohort_export_fails_without_creating_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'bundle';shutil.copytree(FOLDER,folder)
            r=subprocess.run([sys.executable,str(ROOT/'scripts/build_pit_sp500_inputs.py'),'--folder',str(folder),'--export-cohorts'],capture_output=True)
            self.assertEqual(r.returncode,2);self.assertFalse((folder/'origin-cohorts.json').exists())

    def test_replay_preserves_reference_files_and_disables_training(self):
        lock,_=verify_lock(FOLDER)
        self.assertEqual(len(lock['preservedFiles']),1155)
        protocol=read(FOLDER,'PROTOCOL.json')
        self.assertFalse(protocol['modelTrainingAllowed']);self.assertFalse(protocol['productionChangesAllowed'])

if __name__=='__main__':unittest.main()
