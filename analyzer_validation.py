"""Read an integrity-checked, dated research report without fitting models."""
from pathlib import Path
import json
from analyzer_history import fingerprint
from analyzer_support import digest

REPORT='docs/model_validation.json'

def load_report(root):
    path=Path(root)/REPORT
    if path.stat().st_size>2*1024*1024:raise ValueError('Validation artifact is too large')
    value=json.loads(path.read_text(encoding='utf-8'))
    if value.get('schema')!=1 or value.get('integrity')!=fingerprint({k:v for k,v in value.items() if k!='integrity'}):raise ValueError('Validation artifact integrity/schema mismatch')
    return value

def format_validation(value,root=None):
    lines=['MODEL VALIDATION',value['status'], 'Protocol: '+value['protocol_version'],
           'Period: '+value['period']['start']+' through '+value['period']['end'],
           'Frozen holdout begins: '+value['period']['holdout_start']+'; scores and calibration below use holdout bouts only.',
           'Snapshot evaluation includes later source corrections. This is not prospective performance.',
           'Accuracy: fraction of correct choices. Brier score: squared probability error; lower is better.',
           'Accuracy chooses fighter A at probabilities of 50% or higher, including exact 50/50 ties; orientation uses stable IDs.',
           'Log loss penalizes confident errors; lower is better. Calibration compares probability bins with observed outcomes.','']
    if value.get('reviewed_at'):lines.append('Report reviewed: '+value['reviewed_at'])
    if root is not None:
        match=all((Path(root)/p).exists() and digest(Path(root)/p)==sha for p,sha in value.get('datasets',{}).items())
        code_match=all((Path(root)/p).exists() and digest(Path(root)/p)==sha for p,sha in value.get('code',{}).items())
        lines.append('Installed dataset '+('matches evaluated snapshot.' if match else 'differs from evaluated snapshot; results describe the recorded period.'))
        lines.append('Installed engine '+('matches report source.' if code_match else 'differs from evaluated source; report is historical evidence.'))
    lines.extend(value.get('limitations',[]))
    for sex,result in value['models'].items():
        lines+=['',sex.upper()+' — '+result['model_version'],'Evaluated: '+str(result['evaluated'])+'; excluded: '+str(result['excluded'])+'; failed: '+str(result['failed'])+'; remaining: '+str(result['remaining'])]
        lines.append('Scored holdout bouts: '+str(sum(row['count'] for row in result.get('calibration',[]))))
        for name,metrics in result.get('scores',{}).items():lines.append(name+': '+', '.join(k+'='+str(round(v,4)) for k,v in metrics.items()))
        for row in result.get('calibration',[]):lines.append(f"Probability {row['low']:.0%}–{row['high']:.0%}: n={row['count']}, mean forecast={row['mean_probability']}, observed={row['observed_rate']}")
        if result.get('uncertainty'):lines.append('Event-cluster bootstrap: '+str(result['uncertainty'])+'; repeated fighters remain dependent.')
    return '\n'.join(lines)
