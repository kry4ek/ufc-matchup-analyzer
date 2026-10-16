"""Review complete signed research inputs into bounded public aggregates."""
import argparse
from html import escape
import json
import math
from pathlib import Path
import random
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_history import fingerprint,utc_now
from analyzer_support import atomic_json,digest
from analyzer_validation import format_validation

def metrics(rows,field):
    from sklearn.metrics import log_loss,brier_score_loss
    if not rows:return {}
    y=[r['outcome'] for r in rows];p=[r[field] for r in rows]
    return dict(accuracy=sum((v>=.5)==bool(label) for v,label in zip(p,y))/len(rows),
        brier=float(brier_score_loss(y,p)),log_loss=float(log_loss(y,p,labels=[0,1])))

def bins(rows):
    result=[]
    for index in range(5):
        selected=[r for r in rows if index/5<=r['probability']<(index+1)/5 or index==4 and r['probability']==1]
        result.append(dict(low=index/5,high=(index+1)/5,count=len(selected),
            mean_probability=sum(r['probability'] for r in selected)/len(selected) if selected else None,
            observed_rate=sum(r['outcome'] for r in selected)/len(selected) if selected else None))
    return result

def uncertainty(rows):
    dates=sorted({r['event_date'] for r in rows})
    if len(dates)<20:return dict(status='Unavailable: fewer than 20 event-date clusters',clusters=len(dates))
    groups={date:[r for r in rows if r['event_date']==date] for date in dates};rng=random.Random(42);deltas=[]
    for _ in range(1000):
        sample=[r for date in rng.choices(dates,k=len(dates)) for r in groups[date]]
        deltas.append(metrics(sample,'probability')['log_loss']-metrics(sample,'reference')['log_loss'])
    deltas.sort()
    return dict(method='1000 paired event-date bootstrap replicates; seed 42; descriptive 95% interval',
        clusters=len(dates),candidate_minus_reference_log_loss_low=deltas[25],candidate_minus_reference_log_loss_high=deltas[974])

def reviewed(directory,sex,partition):
    protocol=json.loads((directory/'protocol.json').read_text())
    signature=protocol.pop('signature')
    # Evaluator signatures use ASCII JSON, matching its signature function.
    import hashlib
    actual=hashlib.sha256(json.dumps(protocol,sort_keys=True).encode()).hexdigest()
    if actual!=signature:raise ValueError('Protocol signature failed')
    state=json.loads((directory/(sex+'-'+partition+'-checkpoint.json')).read_text())
    if state['signature']!=signature:raise ValueError('Checkpoint signature failed')
    rows=state['rows']
    if len(rows)!=state['planned_bouts'] or len({r['fight_id'] for r in rows})!=len(rows):raise ValueError('Incomplete or duplicate evaluation')
    if any(r['training_max']>=r['event_date'] for r in rows):raise ValueError('Chronological cutoff failed')
    for r in rows:
        if type(r['outcome']) is not int or r['outcome'] not in (0,1):raise ValueError('Invalid scored label')
        for field in ('probability','reference','fifty_fifty','elo'):
            if not math.isfinite(r[field]) or not 0<=r[field]<=1:raise ValueError('Invalid forecast')
    return protocol,signature,state

def verify_snapshot(app,protocols):
    # Do not attach a refreshed snapshot's hashes to historical scores.
    for sex,protocol in protocols.items():
        row=protocol['datasets'][sex]
        if digest(app/row['path'])!=row['sha256']:
            raise ValueError('Report app differs from evaluated '+sex+' training snapshot')
    for rel,sha in protocols['women']['live_code'].items():
        if digest(app/rel)!=sha:
            raise ValueError('Report app differs from evaluated live adapter: '+rel)

def main():
    p=argparse.ArgumentParser();p.add_argument('--women',type=Path,required=True);p.add_argument('--men',type=Path,required=True)
    p.add_argument('--app',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--parity-evidence',type=Path);a=p.parse_args()
    records={};signatures={};protocols={}
    for sex,directory in [('women',a.women),('men',a.men)]:
        records[sex]={}
        for partition in ('development','holdout'):
            protocol,signature,state=reviewed(directory,sex,partition)
            protocols[sex]=protocol;signatures[sex]=signature;records[sex][partition]=state
    audits=[]
    for path in sorted((a.women/'audits').glob('women-*.json')):
        audit=json.loads(path.read_text())
        if audit['status']!='PASS':raise ValueError('Failed fold audit')
        for row in audit['boundaries']:
            if row['overlapping_bouts'] or row['train_max']>=row['test_min']:raise ValueError('Invalid nested boundary')
        audits.append(dict(date=path.stem.removeprefix('women-'),boundaries=len(audit['boundaries']),status='PASS'))
    women_protocol=protocols['women']
    women_holdout=records['women']['holdout']['rows']
    expected_dates={r['event_date'] for partition in ('development','holdout') for r in records['women'][partition]['rows']}
    if {row['date'] for row in audits}!=expected_dates:raise ValueError('Missing or extra model-fold audits')
    if len(women_holdout)<women_protocol['minimum_women_holdout_bouts'] or len({r['event_date'] for r in women_holdout})<women_protocol['minimum_women_holdout_dates']:
        raise ValueError('Holdout coverage gate failed')
    candidate=metrics(women_holdout,'probability');reference=metrics(women_holdout,'reference')
    performance_pass=(candidate['log_loss']<=reference['log_loss']+women_protocol['log_loss_margin'] and
                      candidate['brier']<=reference['brier']+women_protocol['brier_margin'])
    parity_pass=False;parity_sha=None
    if a.parity_evidence:
        parity=json.loads(a.parity_evidence.read_text())
        if (parity.get('status')!='PASS' or {r.get('sex') for r in parity.get('cases',[])}!={'men','women'}
                or any(r.get('status')!='PASS' for r in parity['cases'])):
            raise ValueError('Parent/export parity evidence is incomplete')
        parity_pass=True;parity_sha=digest(a.parity_evidence)
    versions={'men':'v3_bayes_smoothed','women':'v2_chronological_calibrated_ensemble'}
    datasets=json.loads((a.app/'dataset_manifest.json').read_text())
    # Provenance must describe the evaluated snapshot, even when installation
    # datasets have since been refreshed. Never label new data as evaluated.
    verify_snapshot(a.app,protocols)
    value=dict(schema=1,status='LIMITED_RETROSPECTIVE_EVALUATION',reviewed_at=utc_now(),
        protocol_version=women_protocol['version'],period=dict(start=women_protocol['start'],end=women_protocol['end'],holdout_start=women_protocol['holdout_start']),
        protocol_signatures=signatures,datasets={r['path']:digest(a.app/r['path']) for r in datasets['files']},
        code={p.relative_to(a.app).as_posix():digest(p) for name in ('mens_ufc_model','womens_ufc_model') for p in (a.app/name).rglob('*.py') if '__pycache__' not in p.parts},
        cv_audit=dict(status='PASS',audited_event_dates=len(audits),boundaries=sum(r['boundaries'] for r in audits)),
        promotion=dict(performance_gate='PASS' if performance_pass else 'FAIL',
            live_parent_export_parity='PASS' if parity_pass else 'REQUIRES_SEPARATE_VERIFICATION',parity_evidence_sha256=parity_sha,
            decision='PROMOTE_WITH_LIMITED_RETROSPECTIVE_EVIDENCE' if performance_pass and parity_pass else 'DO_NOT_PROMOTE'),
        limitations=['Retrospective installed snapshot includes later source and profile corrections; not prospective performance.',
            'Prior research exposure outside the recorded v0.6 dates is not independently established.',
            'Repeated fighters remain dependent; event-date bootstrap intervals are descriptive.',
            'Women: actual dated app input rows, parent model fitting, installed training snapshot.',
            'Men: stored prefight-row evaluation; end-to-end live behavior requires separate parity checks.',
            'Accuracy and calibration do not establish profitability. Reliability thresholds are not validated for the corrected policy.'],models={})
    for sex in ('men','women'):
        development=records[sex]['development'];holdout=records[sex]['holdout'];rows=holdout['rows']
        value['models'][sex]=dict(model_version=versions[sex],evaluated=len(development['rows'])+len(rows),
            excluded=protocols[sex]['cohorts'][sex]['exposure_bouts'],failed=0,remaining=0,
            planned_bouts=development['planned_bouts']+holdout['planned_bouts'],
            historical_failed_attempts=sum(x['status']=='failed' for state in (development,holdout) for x in state['attempts']),
            interrupted_attempts=sum(x['status']=='interrupted' for state in (development,holdout) for x in state['attempts']),
            scores={label:metrics(rows,field) for label,field in [('Model holdout','probability'),('Frozen reference','reference'),('50/50 holdout','fifty_fifty'),('Elo holdout','elo')]},
            development_scores=metrics(development['rows'],'probability'),calibration=bins(rows),uncertainty=uncertainty(rows),
            event_dates=sorted({r['event_date'] for r in rows}),methodology_audit={'status':'PASS'} if sex=='men' else value['cv_audit'])
    value['integrity']=fingerprint(value);atomic_json(a.out/'model_validation.json',value)
    text=format_validation(value)
    (a.out/'MODEL_VALIDATION.md').write_text('# Model validation — limited retrospective evaluation\n\n```text\n'+text+'\n```\n\nPromotion gates: '+str(value['promotion'])+'\n',encoding='utf-8')
    charts=[]
    for sex,model in value['models'].items():
        charts.append('<h2>'+escape(sex.title())+' final-cohort calibration (n='+str(sum(b['count'] for b in model['calibration']))+')</h2>')
        charts.append('<p>Points describe observed bins; counts and repeated-fighter dependence limit their interpretation.</p><img style="max-width:700px;width:100%" src="images/model-validation-v07-'+sex+'.png" alt="'+sex.title()+' final-cohort calibration with bin counts"><table><tr><th>Bin</th><th>n</th><th>Mean forecast</th><th>Observed rate</th></tr>')
        for b in model['calibration']:charts.append('<tr>'+''.join('<td>'+escape(str(x) if x is not None else 'Unavailable')+'</td>' for x in (f'{b["low"]:.0%}–{b["high"]:.0%}',b['count'],b['mean_probability'],b['observed_rate']))+'</tr>')
        charts.append('</table>')
    (a.out/'MODEL_VALIDATION.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Model validation</title><style>body{font:16px system-ui;max-width:1000px;margin:30px auto;padding:0 20px}pre{white-space:pre-wrap}svg{max-width:520px;width:100%}td,th{border:1px solid #aaa;padding:8px}table{border-collapse:collapse}</style><h1>Limited retrospective evaluation</h1><pre>'+escape(text)+'</pre>'+''.join(charts)+'</html>',encoding='utf-8')
    print(json.dumps(value['promotion'],indent=2))

if __name__=='__main__':main()
