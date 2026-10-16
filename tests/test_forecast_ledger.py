"""Append-only research lifecycle, interruption and identity safeguards."""
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.forecast_ledger import Ledger

class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.ledger=Ledger(self.root)
        self.now=dt.datetime(2026,1,1,tzinfo=dt.timezone.utc)
        self.registration=dict(deadline='2026-01-02T00:00:00Z',event_date='2026-01-02',fighter_a_id='a',fighter_b_id='b',protocol_id='test',cohort_id='dry-run')
        self.ledger.append('registration','bout',self.registration,self.now)
        self.forecast=dict(forecast_id='bout',probability=.7,model_policy='test',code_fingerprint='a'*64,data_fingerprint='b'*64,request={'a':'a','b':'b'})
    def tearDown(self):self.temp.cleanup()
    def test_complete_lifecycle_preserves_forecast_and_correction(self):
        self.ledger.append('failure','attempt1',dict(forecast_id='bout',reason='interrupted'),self.now)
        forecast=self.ledger.append('forecast','attempt2',self.forecast,self.now)
        self.ledger.append('outcome','outcome1',dict(forecast_id='bout',outcome=1),self.now)
        self.ledger.append('correction','correction1',dict(forecast_id='bout',replaces='outcome1',outcome=0),self.now)
        score=Ledger(self.root).score();self.assertEqual(score['scored'],1);self.assertAlmostEqual(score['brier'],.49)
        self.assertEqual(score['failed_attempts'],1);self.assertEqual(score['forecasts_without_timely_external_receipt'],1)
        self.assertEqual(self.ledger.records()[2],forecast)
    def test_retry_identity_is_idempotent_but_cannot_be_rewritten(self):
        value=self.ledger.append('forecast','attempt',self.forecast,self.now)
        self.assertEqual(value,self.ledger.append('forecast','attempt',self.forecast,self.now))
        with self.assertRaises(ValueError):self.ledger.append('forecast','attempt',dict(self.forecast,probability=.9),self.now)
    def test_late_forecast_rejected(self):
        with self.assertRaisesRegex(ValueError,'cutoff'):self.ledger.append('forecast','attempt',self.forecast,self.now+dt.timedelta(days=2))
    def test_partial_pending_write_is_not_a_committed_record(self):
        (self.root/'pending-00000002.json').write_text('{')
        self.assertEqual(len(self.ledger.records()),1)
        self.ledger.append('forecast','attempt',self.forecast,self.now)
        self.assertEqual(len(self.ledger.records()),2)
    def test_tampering_and_receipt_mismatch_rejected(self):
        forecast=self.ledger.append('forecast','attempt',self.forecast,self.now)
        with self.assertRaises(ValueError):self.ledger.append('timestamp_receipt','receipt',dict(forecast_id='bout',record_id='attempt',record_hash='wrong'),self.now)
        path=self.root/'record-00000002.json';record=json.loads(path.read_text());record['payload']['probability']=.9;path.write_text(json.dumps(record))
        with self.assertRaises(ValueError):self.ledger.records()
    def test_outcome_requires_explicit_correction(self):
        self.ledger.append('forecast','attempt',self.forecast,self.now)
        with self.assertRaises(ValueError):self.ledger.append('outcome','invalid',dict(forecast_id='bout',outcome=True),self.now)
        self.ledger.append('outcome','original',dict(forecast_id='bout',outcome=1),self.now)
        with self.assertRaises(ValueError):self.ledger.append('outcome','replacement',dict(forecast_id='bout',outcome=0),self.now)
