import argparse, contextlib, csv, importlib.util, io, json, os, pathlib, sys, tempfile, unittest, zipfile
from unittest import mock

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import analyzer_support as support
import analyzer_maintenance as maintenance
import ufc_matchup_analyzer as cli

class InputTests(unittest.TestCase):
    def test_invalid_dates(self):
        for value in ['2026-02-30','2026-2-01','next week']:
            with self.subTest(value=value),self.assertRaises(argparse.ArgumentTypeError):cli.iso_date(value)
    def test_valid_date(self):self.assertEqual(cli.iso_date('2026-10-10'),'2026-10-10')
    def test_probabilities_and_winner(self):
        base=dict(fighter_a='A',fighter_b='B',fighter_a_win_probability=.6,fighter_b_win_probability=.4,predicted_winner='A',training_rows=10)
        cli.validate_prediction(base)
        for patch in [dict(fighter_a_win_probability=float('nan')),dict(fighter_b_win_probability=.5),dict(predicted_winner='C'),dict(training_rows=0)]:
            with self.subTest(patch=patch),self.assertRaises(ValueError):cli.validate_prediction(dict(base,**patch))
    def test_path_traversal(self):
        for relative in ['../outside','/outside','.']:
            with self.subTest(relative=relative),self.assertRaises(ValueError):support.safe_path(ROOT,relative)
    def test_women_duplicate_identity_is_not_hidden_by_id(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);path=root/'womens_ufc_model/output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv'
            path.parent.mkdir(parents=True)
            path.write_text('fighter,profile_url\nSame Name,http://example/fighter/a\nSame Name,http://example/fighter/b\n')
            with self.assertRaisesRegex(ValueError,'Ambiguous'):cli.resolve_fighter('Same Name','women',root,fighter_id='a')
    @unittest.skipIf(os.environ.get('ANALYZER_SOURCE_ONLY')=='1','Dataset-dependent release test; run with release data')
    def test_unknown_is_not_guessed(self):
        with self.assertRaisesRegex(ValueError,'Fighter not found'):cli.resolve_fighter('Islam Makhaachev','men')
    @unittest.skipIf(os.environ.get('ANALYZER_SOURCE_ONLY')=='1','Dataset-dependent release test; run with release data')
    def test_duplicate_name_requires_id(self):
        with self.assertRaisesRegex(ValueError,'Ambiguous'):cli.resolve_fighter('Bruno Silva','men')
    @unittest.skipIf(os.environ.get('ANALYZER_SOURCE_ONLY')=='1','Dataset-dependent release test; run with release data')
    def test_exact_known_names(self):
        self.assertEqual(cli.resolve_fighter('islam makhachev','men')[0],'Islam Makhachev')
        self.assertEqual(cli.resolve_fighter('Valentina Shevchenko','women')[0],'Valentina Shevchenko')

def mini_root(root):
    (root/'mens_ufc_model/data').mkdir(parents=True)
    path=root/'mens_ufc_model/data/example.csv';path.write_text('event_date,value\n2020-01-01,1\n')
    spec=dict(version='0.1.0',files=[dict(path='mens_ufc_model/data/example.csv',sha256=support.digest(path),size_bytes=path.stat().st_size,rows=1,columns=['event_date','value'],latest_date='2020-01-01')])
    support.atomic_json(root/'dataset_manifest.json',spec)
    return spec

class DatasetTests(unittest.TestCase):
    def test_missing_corrupt_future_empty_and_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);spec=mini_root(root);path=root/spec['files'][0]['path']
            self.assertTrue(all(x['status']=='PASS' for x in support.data_health(root)))
            for contents in ['event_date,value\n2020-01-01,99\n','event_date,value\n2099-01-01,1\n','wrong\n1\n','event_date,value\n']:
                path.write_text(contents);self.assertEqual(support.data_health(root)[0]['status'],'FAIL')
            path.unlink();self.assertEqual(support.data_health(root)[0]['status'],'FAIL')
    def test_archive_install_and_overwrite_refusal(self):
        with tempfile.TemporaryDirectory() as temp:
            base=pathlib.Path(temp);source=base/'source';source.mkdir();spec=mini_root(source);dest=base/'dest';dest.mkdir();support.atomic_json(dest/'dataset_manifest.json',spec)
            archive=base/'data.zip'
            with zipfile.ZipFile(archive,'w') as z:z.write(source/spec['files'][0]['path'],spec['files'][0]['path'])
            support.install_dataset_archive(archive,dest);self.assertEqual(support.data_health(dest)[0]['status'],'PASS')
            with self.assertRaises(ValueError):support.install_dataset_archive(archive,dest)
    def test_archive_validated_before_any_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);spec=mini_root(root);path=root/spec['files'][0]['path'];path.unlink();archive=root/'bad.zip'
            for name,contents in [('../escape','bad'),(spec['files'][0]['path'],'bad')]:
                with zipfile.ZipFile(archive,'w') as z:z.writestr(name,contents)
                with self.assertRaises(ValueError):support.install_dataset_archive(archive,root)
                self.assertFalse(path.exists())

class TransactionTests(unittest.TestCase):
    def test_commit_undo_and_old_undo_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);spec=mini_root(root);path=root/spec['files'][0]['path'];before=path.read_bytes()
            def runner(cmd,cwd,log):pass
            def validator(stage,sex,logs,runner):
                (stage/'mens_ufc_model/data/example.csv').write_text('event_date,value\n2020-01-01,2\n')
            first=maintenance.maintenance(root,kind='rebuild',target='men',runner=runner,validator=validator)
            self.assertNotEqual(path.read_bytes(),before)
            self.assertEqual(support.data_health(root)[0]['status'],'PASS')
            second=maintenance.maintenance(root,kind='rebuild',target='men',runner=runner,validator=validator)
            with self.assertRaisesRegex(RuntimeError,'most recent'):maintenance.recover(root,first)
            maintenance.recover(root,second);maintenance.recover(root,first)
            self.assertEqual(path.read_bytes(),before)
    def test_second_target_failure_preserves_both(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);spec=mini_root(root)
            women=root/'womens_ufc_model/output/example.csv';women.parent.mkdir(parents=True);women.write_text('event_date,value\n2020-01-01,1\n')
            spec['files'].append(dict(path=women.relative_to(root).as_posix(),sha256=support.digest(women),size_bytes=women.stat().st_size,rows=1,columns=['event_date','value']))
            support.atomic_json(root/'dataset_manifest.json',spec);before={x['path']:(root/x['path']).read_bytes() for x in spec['files']}
            def runner(cmd,cwd,log):
                if cwd.name=='womens_ufc_model':raise RuntimeError('second model failed')
                (cwd/'data/example.csv').write_text('staged change')
            with self.assertRaises(RuntimeError):maintenance.maintenance(root,kind='rebuild',runner=runner,validator=lambda *x:None)
            for rel,contents in before.items():self.assertEqual((root/rel).read_bytes(),contents)
    def test_incomplete_missing_and_malformed_audits(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp)
            with self.assertRaises(RuntimeError):maintenance.validate_update_audits(root)
            audit=root/'_update_manifests/run';audit.mkdir(parents=True)
            support.atomic_json(audit/'new_rows_safety_audit.json',{})
            with self.assertRaises(RuntimeError):maintenance.validate_update_audits(root)
            support.atomic_json(audit/'new_rows_safety_audit.json',dict(unsafe_rows_count=0))
            for status in ['event_fetch_error','fight_fetch_error','skipped_future_event','skipped_unresolved_result']:
                (audit/'events_inspected.csv').write_text('status\n'+status+'\n')
                with self.subTest(status=status),self.assertRaises(RuntimeError):maintenance.validate_update_audits(root)
    def test_dry_run_no_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);spec=mini_root(root);path=root/spec['files'][0]['path'];before=path.read_bytes()
            def runner(cmd,cwd,log):
                audit=cwd/'_update_manifests/run';audit.mkdir(parents=True);support.atomic_json(audit/'new_rows_safety_audit.json',dict(unsafe_rows_count=0))
                (cwd/'data/example.csv').write_text('event_date,value\n2020-01-01,2\n')
            maintenance.maintenance(root,target='men',runner=runner)
            self.assertEqual(path.read_bytes(),before);self.assertFalse((root/'.runtime/maintenance.lock').exists())
            self.assertEqual(len(list((root/'.runtime/transactions').glob('*/audits/men/run/new_rows_safety_audit.json'))),1)
    def test_network_or_rebuild_failure_preserves_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);spec=mini_root(root);path=root/spec['files'][0]['path'];before=path.read_bytes()
            def runner(cmd,cwd,log):
                (cwd/'data/example.csv').write_text('mutated staging only')
                raise RuntimeError('simulated network or rebuild failure')
            for kind in ['update','rebuild']:
                with self.assertRaises(RuntimeError):maintenance.maintenance(root,kind=kind,target='men',apply=True,runner=runner,validator=lambda *x:None)
                self.assertEqual(path.read_bytes(),before)
    def test_unsafe_source_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);spec=mini_root(root);path=root/spec['files'][0]['path'];before=path.read_bytes()
            def runner(cmd,cwd,log):
                audit=cwd/'_update_manifests/run';audit.mkdir(parents=True);support.atomic_json(audit/'new_rows_safety_audit.json',dict(unsafe_rows_count=2))
            with self.assertRaisesRegex(RuntimeError,'Unsafe'):maintenance.maintenance(root,target='men',apply=True,runner=runner,validator=lambda *x:None)
            self.assertEqual(path.read_bytes(),before)
    def test_commit_recovery_and_crash_intent(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);mini_root(root);txn=root/'.runtime/transactions/test';stage=txn/'stage';stage.mkdir(parents=True)
            rel='mens_ufc_model/data/example.csv';dest=root/rel;before=dest.read_bytes();(stage/rel).parent.mkdir(parents=True);(stage/rel).write_text('new content')
            journal=dict(id='test',status='staging',promotions=[])
            maintenance.promote(root,stage,txn,journal,[rel]);self.assertEqual(dest.read_text(),'new content')
            maintenance.rollback(root,txn,journal);self.assertEqual(dest.read_bytes(),before)
            self.assertEqual(json.loads((txn/'journal.json').read_text())['status'],'rolled_back')
    def test_active_process_and_traversal_recovery_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);(root/'.runtime').mkdir();support.atomic_json(root/'.runtime/maintenance.lock',dict(pid=123,transaction='test'))
            with mock.patch.object(maintenance,'process_alive',return_value=True),self.assertRaises(RuntimeError):maintenance.recover(root)
            with mock.patch.object(maintenance,'process_alive',return_value=False),self.assertRaises(ValueError):maintenance.recover(root,'../bad')

class ReleaseGateTests(unittest.TestCase):
    def test_permission_and_unverified_checks_block_publication(self):
        from tools.package_release import gate
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);spec=mini_root(root)
            spec.update(redistribution_status='review_required',release_repository='owner/ufc-matchup-analyzer')
            support.atomic_json(root/'dataset_manifest.json',spec)
            checks=[dict(name='required local check',status='PASS'),dict(name='public download',phase='after_publish',status='UNVERIFIED')]
            support.atomic_json(root/'release_checks.json',dict(checks=checks))
            with self.assertRaisesRegex(ValueError,'redistribution'):gate(root)
            spec['redistribution_status']='cleared';support.atomic_json(root/'dataset_manifest.json',spec)
            checks[0]['status']='UNVERIFIED';support.atomic_json(root/'release_checks.json',dict(checks=checks))
            with self.assertRaisesRegex(ValueError,'required local check'):gate(root)
            checks[0]['status']='PASS';support.atomic_json(root/'release_checks.json',dict(checks=checks))
            gate(root)
            spec['release_repository']=None;support.atomic_json(root/'dataset_manifest.json',spec)
            with self.assertRaisesRegex(ValueError,'pinned data URL'):gate(root)

class UpdaterAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pandas as pd
        cls.pd=pd;sys.path.insert(0,str(ROOT/'mens_ufc_model'))
        cls.modules={}
        for sex,file in [('men','mens_ufc_model/update_ufc_mens_dataset_incremental.py'),('women','womens_ufc_model/update_ufc_womens_dataset_incremental.py')]:
            spec=importlib.util.spec_from_file_location('audit_'+sex,ROOT/file);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);cls.modules[sex]=module
    def rows(self):
        return self.pd.DataFrame([dict(fight_id='new',fighter_id='a',fighter_name='A',fighter='A',event_date='2020-01-01',result='win',won=1,result_marker='W'),dict(fight_id='new',fighter_id='b',fighter_name='B',fighter='B',event_date='2020-01-01',result='loss',won=0,result_marker='L')])
    def audit(self,sex,rows,existing=set()):
        args=[rows,existing,self.pd.Timestamp('2026-09-30'),False]
        if sex=='men':args.insert(0,self.pd.DataFrame([dict(fight_id='new',result='win_loss')]))
        return self.modules[sex].audit_new_rows_for_apply(*args)
    def test_valid_new_and_no_changes(self):
        for sex in self.modules:
            self.assertEqual(self.audit(sex,self.rows())['unsafe_rows_count'],0)
            if sex=='women':self.assertEqual(self.audit(sex,self.pd.DataFrame())['unsafe_rows_count'],0)
    def test_future_duplicate_unresolved_and_one_sided(self):
        for sex in self.modules:
            for case in ['future','duplicate','unresolved','one-sided']:
                rows=self.rows();existing=set()
                if case=='future':rows['event_date']='2099-01-01'
                if case=='duplicate':existing={'new'}
                if case=='unresolved':rows['result']='';rows['won']=float('nan');rows['result_marker']=''
                if case=='one-sided':rows=rows.iloc[:1]
                with self.subTest(sex=sex,case=case):self.assertGreater(self.audit(sex,rows,existing)['unsafe_rows_count'],0)
    def test_event_parser_fixture(self):
        from bs4 import BeautifulSoup
        html='<table><tr><td><a href="http://ufcstats.com/event-details/abcd">UFC Example</a></td><td>September 26, 2026</td><td>Example City</td></tr></table>'
        for module in self.modules.values():
            parsed=module.parse_event_list(BeautifulSoup(html,'lxml'));self.assertEqual(len(parsed),1);self.assertEqual(str(parsed[0]['event_date'].date()),'2026-09-26')
    def test_future_events_do_not_consume_event_limit(self):
        events=[dict(event_date=self.pd.Timestamp(day)) for day in ['2026-10-03','2026-09-28','2026-09-26']]
        for module in self.modules.values():
            selected=module.select_completed_events(events,self.pd.Timestamp('2026-09-27'),self.pd.Timestamp('2026-09-30'),1)
            self.assertEqual([x['event_date'].date().isoformat() for x in selected],['2026-09-28'])
            self.assertEqual(module.select_completed_events(events,self.pd.Timestamp('2026-09-29'),self.pd.Timestamp('2026-09-30'),1),[])

if __name__=='__main__':unittest.main()
