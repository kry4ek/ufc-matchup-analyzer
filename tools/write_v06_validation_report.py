"""Publish reviewed static aggregates from a completed local evaluation."""
import argparse
from html import escape
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_support import atomic_json,digest
from analyzer_history import fingerprint,utc_now
from analyzer_validation import format_validation

FOLLOWUP='''The next model research cycle must keep mirrored bout pairs together in ensemble and calibration folds, use chronological outer evaluation, and audit calibration on disjoint bout groups. Compare against the frozen current policy without retuning this holdout. Promote a changed model only after a separate protocol and evaluation.

A prospective research ledger should record each forecast, request, model/data fingerprints and timestamp before an event, then append outcomes and scores afterward. Retain every planned forecast and failure. Independently verifiable publication timestamps are needed for a prospective claim; local clocks and the app's prunable recent-history list are insufficient. Do not rewrite earlier forecasts.'''

def main():
    p=argparse.ArgumentParser();p.add_argument('--evaluation',type=Path,required=True);a=p.parse_args()
    original=a.evaluation/'model_validation.json';value=json.loads(original.read_text(encoding='utf-8'))
    if value['integrity']!=fingerprint({k:v for k,v in value.items() if k!='integrity'}):raise ValueError('Evaluation integrity failed')
    checkpoint=json.loads((a.evaluation/'checkpoint.json').read_text(encoding='utf-8'))
    if any(m['remaining'] or m['failed'] for m in value['models'].values()):raise ValueError('Evaluation is incomplete')
    value.update(reviewed_at=utc_now(),parent_report_sha256=digest(original),protocol_signature=checkpoint['signature'],protocol=checkpoint['protocol'])
    value['integrity']=fingerprint({k:v for k,v in value.items() if k!='integrity'});atomic_json(ROOT/'docs/model_validation.json',value)
    text=format_validation(value)
    protocol='One decisive bout per observation; fighter orientation uses stable IDs. Development precedes 26 September 2026. The 26 September holdout was frozen before scoring; no tuning. Training excludes the selected date and later. Five fixed probability bins; log-loss clipping at 1e-12. Baselines use 50/50 and unmodified pre-bout Elo expected scores. Event-aware uncertainty is unavailable with fewer than five event/date clusters. Repeated fighters can remain dependent.'
    md='# Model validation — limited retrospective evaluation\n\nReviewed: '+value['reviewed_at']+'\n\n'+protocol+'\n\n```text\n'+text+'\n```\n\n[Offline calibration diagrams](MODEL_VALIDATION.html) include every bin and its sample count. Empty bins remain unavailable.\n\n## Next research cycle\n\n'+FOLLOWUP+'\n'
    (ROOT/'docs/MODEL_VALIDATION.md').write_text(md,encoding='utf-8')
    charts=[]
    for sex,model in value['models'].items():
        bins=model['calibration'];count=sum(b['count'] for b in bins)
        charts.append('<h2>'+sex.title()+f' holdout calibration (n={count})</h2><p>Small retrospective sample; points are descriptive. The dashed line represents equal forecast and observed rates.</p>')
        charts.append('<svg viewBox="0 0 520 330" role="img" aria-label="'+sex+' holdout calibration"><path d="M60 30V270H470M60 270L470 30" fill="none" stroke="#888" stroke-dasharray="4 4"/>')
        for label,x,y in [('0%',40,285),('100%',435,292),('100%',8,40),('Mean forecast',190,319),('Observed rate',8,17)]:charts.append(f'<text x="{x}" y="{y}" font-size="14">{label}</text>')
        for b in bins:
            if not b['count']:continue
            x=60+b['mean_probability']*410;y=270-b['observed_rate']*240
            charts.append(f'<circle cx="{x:.3f}" cy="{y:.3f}" r="5" fill="#286a9a"/><text x="{max(60,min(425,x+8)):.3f}" y="{max(45,y-10):.3f}" font-size="14">n={b["count"]}</text>')
        charts.append('</svg><table><tr><th>Bin</th><th>n</th><th>Mean forecast</th><th>Observed rate</th></tr>')
        for b in bins:charts.append('<tr>'+''.join('<td>'+escape(str(x) if x is not None else 'Unavailable')+'</td>' for x in (f'{b["low"]:.0%}–{b["high"]:.0%}',b['count'],b['mean_probability'],b['observed_rate']))+'</tr>')
        charts.append('</table>')
    html='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Dated model validation</title><style>body{font:16px system-ui;max-width:900px;margin:32px auto;padding:0 20px;line-height:1.5}pre{white-space:pre-wrap}svg{max-width:520px;width:100%}td,th{border:1px solid #aaa;padding:8px}table{border-collapse:collapse}</style><h1>Limited retrospective evaluation</h1><p>'+escape(protocol)+'</p><pre>'+escape(text)+'</pre>'+''.join(charts)+'<h2>Next research cycle</h2><p>'+escape(FOLLOWUP).replace('\n\n','</p><p>')+'</p></html>'
    (ROOT/'docs/MODEL_VALIDATION.html').write_text(html,encoding='utf-8')
    print('Installed reviewed aggregates and offline calibration diagrams.')
if __name__=='__main__':main()
