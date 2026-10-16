"""Saved evidence, evaluation provenance, export and native UI contracts."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from analyzer_evidence import build_evidence,evaluation_status,format_evidence,validate_evidence
from analyzer_history import fingerprint
from analyzer_reporting import format_html
from analyzer_results import format_result
from analyzer_support import atomic_json
from analyzer_validation import load_report
from test_gui import result,FakeController

def context():
    return dict(engine='v1_current_ensemble',datasets={'womens_ufc_model/data.csv':'a'*64},
                code={'womens_ufc_model/engine.py':'b'*64})

def report():
    return dict(schema=1,status='LIMITED_RETROSPECTIVE_EVALUATION',integrity='c'*64,
        datasets=context()['datasets'],code=context()['code'],models={'women':dict(model_version='v1_current_ensemble',calibration=[{'count':3}])},
        cv_audit={'status':'FAIL'},limitations=['Mirrored fold overlap'],protocol_version='example')

def payload():
    value=result();value.update(model_version='v1_current_ensemble',result_state='complete',
        calculation_request={'sex':'women','effective_cutoff':'2026-01-01'},
        coverage={'a':dict(fights=0,division_fights=0,latest=None),'b':dict(fights=9,division_fights=3,latest='2025-12-01')})
    value['fighter_a_comparison']={'sig_str_accuracy_before_bayes_s20_den_before':0}
    value['evidence_quality']=build_evidence(value,context(),[dict(status='PASS',latest_date='2025-12-01')],report())
    return value

class EvidenceTests(unittest.TestCase):
    def test_matching_hashes_do_not_clear_methodology_failure(self):
        status=evaluation_status(report(),context(),'women')
        self.assertEqual(status['compatibility'],'matches');self.assertEqual(status['methodology'],'FAIL')
        self.assertIn('Methodology audit failed',format_evidence(payload()))
    def test_empty_provenance_never_matches(self):
        value=report();value.update(code={},datasets={})
        self.assertEqual(evaluation_status(value,context(),'women')['compatibility'],'unknown')
    def test_engine_data_and_policy_are_distinct(self):
        for key,expected in [('code','different_engine'),('datasets','different_data'),('engine','different_model')]:
            current=context();current[key]='another' if key=='engine' else {}
            self.assertEqual(evaluation_status(report(),current,'women')['compatibility'],expected)
        current=context();current['engine']='v2_chronological_calibrated_ensemble'
        status=evaluation_status(report(),current,'women')
        self.assertEqual(status['evaluated_methodology'],'FAIL')
        self.assertEqual(status['methodology'],'NOT_ESTABLISHED')
    def test_zero_bouts_and_zero_attempts_have_explicit_meanings(self):
        value=payload();text=format_evidence(value)
        self.assertIn('0 eligible UFC bouts',text);self.assertIn('prior-only',text)
        self.assertEqual(value['evidence_quality']['metric_support'][0]['attempts'],0)
    def test_men_support_uses_observed_attempts_and_excludes_population_priors(self):
        value=payload()
        value['fighter_a_comparison']={'v3_bayes_sig_str_acc_denominator_before':307.,
            'v3_bayes_td_acc_denominator_before':0.,'v3_bayes_sig_str_acc_prior_denominator':98649.,
            'sig_str_accuracy_smoothed_prior_den_before':98649.}
        value['evidence_quality']=build_evidence(value,context(),[],report())
        rows=value['evidence_quality']['metric_support']
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['attempts'],307.)
        self.assertEqual(rows[1]['status'],'prior_only')
        text=format_evidence(value)
        self.assertIn('Significant strike accuracy: 307 attempts',text)
        self.assertNotIn('98649',text)
    def test_missing_facts_do_not_become_zero(self):
        value=payload();value['evidence_quality']['fighters']['a']['eligible_bouts']=None
        self.assertIn('Unavailable eligible UFC bouts',format_evidence(value))
        self.assertIn('not recorded',format_evidence(result()))
    def test_exports_use_frozen_facts_and_escape_names(self):
        value=payload();value['evidence_quality']['fighters']['a']['name']='<script>A</script>'
        snapshot=copy.deepcopy(value)
        self.assertIn('0 eligible UFC bouts',format_result(value))
        html=format_html(value);self.assertIn('&lt;script&gt;A&lt;/script&gt;',html)
        self.assertNotIn('<script>A</script>',html);self.assertEqual(value,snapshot)
    def test_partial_has_no_invented_probability(self):
        value=payload();value['result_state']='initial'
        for key in ('fighter_a_win_probability','fighter_b_win_probability','predicted_winner'):value.pop(key,None)
        evidence=build_evidence(value,context(),[],report())
        self.assertEqual(evidence['scope'],'initial');self.assertNotIn('probability',evidence)
    def test_invalid_importable_record_rejected(self):
        value=payload()['evidence_quality'];value['fighters']['a']['eligible_bouts']=-1
        with self.assertRaises(ValueError):validate_evidence(value)
    def test_invalid_attempt_support_cannot_be_imported_as_evidence(self):
        for attempts,status in [(-1,'observed_attempts'),(float('nan'),'observed_attempts'),
                                (True,'observed_attempts'),(0,'observed_attempts'),(3,'prior_only')]:
            with self.subTest(attempts=attempts,status=status):
                value=payload()['evidence_quality']
                value['metric_support'][0].update(attempts=attempts,status=status)
                with self.assertRaises(ValueError):validate_evidence(value)
    def test_validation_path_cannot_leave_root(self):
        with tempfile.TemporaryDirectory() as folder:
            value=report();value.update(period={},datasets={'../escape':'a'*64})
            value['integrity']=fingerprint({k:v for k,v in value.items() if k!='integrity'})
            atomic_json(Path(folder)/'docs/model_validation.json',value)
            with self.assertRaises(ValueError):load_report(folder)
    def test_report_cannot_label_refreshed_data_or_changed_adapter_as_evaluated(self):
        from tools.write_v07_validation_report import verify_snapshot
        from analyzer_support import digest
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);protocols={}
            for sex in ('men','women'):
                path=root/(sex+'.csv');path.write_text('evaluated snapshot')
                protocols[sex]={'datasets':{sex:dict(path=path.name,sha256=digest(path))}}
            adapter=root/'adapter.py';adapter.write_text('evaluated adapter')
            protocols['women']['live_code']={adapter.name:digest(adapter)}
            verify_snapshot(root,protocols)
            (root/'women.csv').write_text('refreshed snapshot')
            with self.assertRaisesRegex(ValueError,'training snapshot'):verify_snapshot(root,protocols)
            (root/'women.csv').write_text('evaluated snapshot');adapter.write_text('changed adapter')
            with self.assertRaisesRegex(ValueError,'live adapter'):verify_snapshot(root,protocols)

class EvidenceWindowTests(unittest.TestCase):
    def test_overview_uses_the_displayed_saved_report(self):
        import analyzer_gui as gui
        window=gui.tk.Tk();window.withdraw()
        folder=tempfile.TemporaryDirectory()
        app=gui.AnalyzerApp(window,root=Path(folder.name),controller=FakeController(),autostart=False)
        try:
            value=payload();app.display_result(value)
            text=app.evidence_panel.text()
            self.assertIn('0 eligible UFC bouts',text)
            app.names['a'].set('Another fighter');window.update()
            self.assertEqual(text,app.evidence_panel.text())
            app.display_result(result());self.assertIn('not recorded',app.evidence_panel.text())
        finally:app.destroy();folder.cleanup()
