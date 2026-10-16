"""Refresh version/provenance bookkeeping while preserving historical evidence."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import atomic_json,digest

def main():
    for name in ('release_checks','verification_evidence'):
        old=ROOT/(name+'.json');target=ROOT/'docs'/(name+'_v07.json')
        if not target.exists():target.write_bytes(old.read_bytes())
    path=ROOT/'dataset_manifest.json';data=json.loads(path.read_text());data['version']='0.8.0';atomic_json(path,data)
    path=ROOT/'source_manifest.json';data=json.loads(path.read_text())
    changes=json.loads((ROOT/'work/v0.8/parent-originals/export.json').read_text())['files']
    for change in changes:
        item=next(i for i in data['files'] if i['path']==change['path'])
        item['source_sha256']=change['parent_sha256'];item['exported_sha256']=digest(ROOT/change['path'])
    text='v0.8 audited parent row iteration preserves dated histories and totals while avoiding per-row Series construction'
    if text not in data['adaptations']:data['adaptations'].append(text)
    atomic_json(path,data)
    # Fresh facts only; final checks will replace pending statuses.
    atomic_json(ROOT/'release_checks.json',dict(version='0.8.0',status='local_experimental_candidate',checks=[
        dict(name='Integrated app regression',status='PASS',required=True),
        dict(name='Native v0.8 interaction and frozen-report checks',status='PASS',required=True),
        dict(name='Parent full-history parity',status='PASS',required=True),
        dict(name='Final end-to-end benchmarks and prediction parity',status='PENDING',required=True),
        dict(name='Local portable/source archive verification',status='PENDING',required=True),
        dict(name='Clean Windows 10/11',status='DEFERRED',required=True),
        dict(name='Actual alternate Windows display scaling',status='DEFERRED',required=True),
        dict(name='Dataset rights',status='review_required',required=True),
        dict(name='Signing / stable release',status='PENDING',required=True),
        dict(name='Publication and remote CI',status='NOT_REQUESTED',phase='after_publish',required=True)]))
if __name__=='__main__':main()
