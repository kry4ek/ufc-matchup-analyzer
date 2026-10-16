"""Append-only local research records; external timestamps remain explicit.

Individual immutable JSON records avoid partially appended JSONL recovery.
An OS file lock is released on process exit, including interrupted writes.
"""
from __future__ import annotations
import argparse
import contextlib
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()

def timestamp(value):
    result=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:raise ValueError('Timezone required')
    return result.astimezone(dt.timezone.utc)

@contextlib.contextmanager
def locked(root):
    root.mkdir(parents=True,exist_ok=True)
    with (root/'ledger.lock').open('a+b') as stream:
        stream.seek(0)
        if stream.read(1)==b'':stream.write(b'0');stream.flush()
        stream.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)

class Ledger:
    def __init__(self,root):self.root=Path(root)
    def records(self):
        result=[];previous=None
        for number,path in enumerate(sorted(self.root.glob('record-*.json')),1):
            record=json.loads(path.read_text(encoding='utf-8'))
            checksum=record.pop('integrity',None)
            if record.get('sequence')!=number or record.get('previous')!=previous or digest(record)!=checksum:
                raise ValueError('Ledger integrity or sequence failure')
            record['integrity']=checksum;result.append(record);previous=checksum
        return result
    def append(self,kind,identity,payload,now=None):
        if kind not in ('registration','forecast','failure','timestamp_receipt','outcome','correction'):
            raise ValueError('Unsupported ledger record kind')
        if not isinstance(identity,str) or not identity or len(identity)>200 or not isinstance(payload,dict):
            raise ValueError('Invalid ledger record')
        now=now or dt.datetime.now(dt.timezone.utc);now=timestamp(now.isoformat())
        with locked(self.root):
            records=self.records();existing=[r for r in records if r['kind']==kind and r['identity']==identity]
            if existing:
                if existing[0]['payload']==payload:return existing[0]
                raise ValueError('Record identity already spent with different content')
            registrations={r['identity']:r for r in records if r['kind']=='registration'}
            if kind=='registration':
                for field in ('deadline','event_date','fighter_a_id','fighter_b_id','protocol_id','cohort_id'):
                    if not payload.get(field):raise ValueError('Missing registration '+field)
                if payload['fighter_a_id']==payload['fighter_b_id']:raise ValueError('Distinct fighter identities required')
                if now>=timestamp(payload['deadline']):raise ValueError('Registration cutoff passed')
                dt.date.fromisoformat(payload['event_date'])
            else:
                registration=registrations.get(payload.get('forecast_id'))
                if not registration:raise ValueError('Unknown registered forecast')
                if kind in ('forecast','failure'):
                    if now>=timestamp(registration['payload']['deadline']):raise ValueError('Pre-event cutoff passed')
                    if any(r['kind']=='forecast' and r['payload'].get('forecast_id')==payload['forecast_id'] for r in records):
                        raise ValueError('A completed forecast already exists')
                if kind=='forecast':
                    p=payload.get('probability')
                    if type(p) not in (int,float) or not math.isfinite(p) or not 0<=p<=1:raise ValueError('Invalid probability')
                    for field in ('model_policy','code_fingerprint','data_fingerprint','request'):
                        if not payload.get(field):raise ValueError('Missing forecast '+field)
                if kind=='outcome':
                    if type(payload.get('outcome')) not in (int,str) or payload.get('outcome') not in (0,1,'draw','no_contest','cancelled'):
                        raise ValueError('Invalid observed outcome')
                    if any(r['kind']=='outcome' and r['payload']['forecast_id']==payload['forecast_id'] for r in records):raise ValueError('Outcome exists; append an explicit correction')
                if kind=='correction':
                    if not payload.get('replaces') or not any(r['identity']==payload['replaces'] and r['kind'] in ('outcome','correction') and r['payload']['forecast_id']==payload['forecast_id'] for r in records):
                        raise ValueError('Correction must reference an existing outcome')
                    if type(payload.get('outcome')) not in (int,str) or payload.get('outcome') not in (0,1,'draw','no_contest','cancelled'):raise ValueError('Invalid corrected outcome')
                if kind=='timestamp_receipt':
                    target=next((r for r in records if r['kind']=='forecast' and r['identity']==payload.get('record_id')),None)
                    if target is None or payload.get('record_hash')!=target['integrity']:
                        raise ValueError('Receipt does not match a completed forecast')
                    if target['payload']['forecast_id']!=payload['forecast_id']:raise ValueError('Receipt forecast mismatch')
                    if not payload.get('url') or not payload.get('provider'):raise ValueError('Missing external timestamp provenance')
                    timestamp(payload['external_time'])
            record=dict(schema=1,sequence=len(records)+1,kind=kind,identity=identity,payload=payload,
                recorded_at=now.isoformat(),previous=records[-1]['integrity'] if records else None)
            record['integrity']=digest(record)
            path=self.root/f"record-{record['sequence']:08d}.json"
            temp=self.root/f"pending-{record['sequence']:08d}.json"
            # A crashed pending write can be replaced; committed records cannot.
            with temp.open('w',encoding='utf-8') as stream:
                json.dump(record,stream,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
            if path.exists():raise ValueError('Sequence already committed')
            os.replace(temp,path)
            return record
    def score(self):
        records=self.records();registrations={r['identity']:r for r in records if r['kind']=='registration'}
        forecasts={r['payload']['forecast_id']:r for r in records if r['kind']=='forecast'}
        outcomes={r['payload']['forecast_id']:r['payload']['outcome'] for r in records if r['kind'] in ('outcome','correction')}
        rows=[];unverified=0
        for identity,forecast in forecasts.items():
            outcome=outcomes.get(identity)
            receipts=[r for r in records if r['kind']=='timestamp_receipt' and r['payload']['record_hash']==forecast['integrity']]
            timely=any(timestamp(r['payload']['external_time'])<timestamp(registrations[identity]['payload']['deadline']) for r in receipts)
            if outcome in (0,1) and type(outcome) is int:
                rows.append(dict(forecast_id=identity,probability=forecast['payload']['probability'],outcome=outcome,
                    external_timestamp_claim=timely))
            if not timely:unverified+=1
        brier=sum((r['probability']-r['outcome'])**2 for r in rows)/len(rows) if rows else None
        return dict(registered=len(registrations),completed=len(forecasts),failed_attempts=sum(r['kind']=='failure' for r in records),
            without_forecast=len(set(registrations)-set(forecasts)),resolved=len(outcomes),scored=len(rows),brier=brier,
            forecasts_without_timely_external_receipt=unverified,
            status='LOCAL_RESEARCH_LEDGER',
            limitation='Receipt fields are recorded claims; independently verify provider evidence before any prospective-performance claim.',rows=rows)

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True)
    sub=p.add_subparsers(dest='command',required=True)
    append=sub.add_parser('append');append.add_argument('--kind',required=True);append.add_argument('--id',required=True);append.add_argument('--payload',type=Path,required=True)
    sub.add_parser('check');sub.add_parser('score');a=p.parse_args();ledger=Ledger(a.root)
    result=ledger.append(a.kind,a.id,json.loads(a.payload.read_text())) if a.command=='append' else ledger.score() if a.command=='score' else dict(records=len(ledger.records()),status='PASS')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
