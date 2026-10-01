"""Shared structured comparison values for native tables and offline exports."""
from __future__ import annotations
from html import escape
from analyzer_results import METRICS, _snapshots, _lookup, _number, _value, _bayes_metrics

OVERVIEW = ('Age (years)', 'Reach (cm)', 'Overall Elo', 'Division Elo', 'UFC fights', 'UFC win rate (%)',
            'Sig. strikes landed / min', 'Sig. strikes absorbed / min', 'Takedowns landed / 15 min',
            'Takedown defense (%)', 'Last 3 win rate (%)', 'Days since last fight')

def explanation(label, field, unit):
    if 'Elo' in label:
        text = 'Internal UFC-results rating; not an official ranking. Overall and division Elo start at 1500. Opponent ratings describe the strength of the recorded schedule.'
    elif 'support' in label:
        text = 'Observed attempt denominator supporting the estimate; this is not the number of fights. Zero attempts means the estimate may come entirely from its prior.'
    elif 'prior' in label or 'weighted' in label:
        text = 'Smoothed rates combine dated attempts with the existing model prior. Elo-weighted performance weights per-fight differentials by opponent pre-fight Elo. Neither is another win probability.'
    elif 'Last 3' in label or 'Last 5' in label:
        text = 'Uses up to the last three or five available eligible UFC fights; short histories use fewer observations.'
    elif label.startswith('Age') or 'Height' in label or 'Reach' in label or 'Stance' in label:
        text = 'Profile measurement used by the engine; age is calculated on the selected fight date. Profile measurements may reflect later source corrections.'
    elif 'win rate' in label:
        text = 'UFC wins divided by wins plus losses for the indicated history; draws and no contests are excluded. Division rates use the selected division.'
    elif 'method' in field or 'wins' in field or 'losses' in field:
        text = 'Recorded UFC history only. Method coverage can be incomplete; missing values must not be interpreted as zero.'
    else:
        text = 'Calculated by the retained engine from eligible UFC history before the selected fight date. Net output is the fighter’s output minus opponents’ output.'
    lower = ('absorbed' in label.casefold() or 'allowed' in label.casefold())
    higher = any(t in label.casefold() for t in ('accuracy', 'defense', 'landed /', 'win rate', 'overall elo', 'division elo')) and not lower
    direction = 'Lower generally favorable' if lower else 'Higher generally favorable' if higher else 'Context dependent'
    if unit == 'percent': text += ' Percentage differences are percentage points (pp).'
    return text + ' ' + direction + '; A−B is a difference, not a guaranteed advantage.', direction

def metric(label, fields, unit, snapshots):
    raw = [_lookup(s, fields) for s in snapshots]
    a, b = [_number(v) for v in raw]
    diff = a-b if a is not None and b is not None and unit not in ('text', 'flag') else None
    notes = []
    for side, snapshot, value in zip(('A', 'B'), snapshots, raw):
        if label == 'Division Elo' and _number(value) == 1500 and _number(snapshot.get('fights_in_division_before')) == 0:
            notes.append(side+': baseline; no selected-division history')
        if 'prior' in label:
            if fields.startswith('v3_bayes_'):
                prefix = fields.split('_s20')[0].split('_s50')[0].split('_current_men')[0].split('_support_scaled')[0]
                den = snapshot.get(prefix+'_denominator_before')
            else: den = snapshot.get(fields+'_den_before')
            if _number(den) == 0: notes.append(side+': prior-only estimate; zero supporting attempts')
    help_text, direction = explanation(label, fields, unit)
    return dict(label=label, fields=fields, unit=unit, raw_a=raw[0], raw_b=raw[1], raw_difference=diff,
                a=_value(raw[0],unit), b=_value(raw[1],unit), difference='—' if unit in ('text','flag') else _value(diff,unit,True),
                explanation=help_text, direction=direction, support_notes=notes)

def report_sections(payload):
    snapshots = _snapshots(payload)
    sections = []
    section = None
    for line in METRICS.splitlines():
        if '|' not in line:
            section = dict(title=line, rows=[]); sections.append(section)
        else:
            label, fields, unit = line.split('|')
            if any(field in s for field in fields.split(',') for s in snapshots):
                section['rows'].append(metric(label,fields,unit,snapshots))
    bayes = _bayes_metrics(snapshots,payload.get('model_version','').startswith('v3'))
    if bayes: sections.append(dict(title='BAYESIAN MODEL RATE ESTIMATES',rows=[metric(*m,snapshots) for m in bayes]))
    return [s for s in sections if s['rows']]

def overview_rows(payload):
    all_rows = {r['label']:r for s in report_sections(payload) for r in s['rows']}
    specs = {line.split('|')[0]:line.split('|')[1:] for line in METRICS.splitlines() if '|' in line}
    snapshots = _snapshots(payload)
    return [all_rows[label] if label in all_rows else metric(label,*specs[label],snapshots) for label in OVERVIEW]

def format_html(payload):
    from analyzer_results import format_result
    title = payload['fighter_a']+' vs '+payload['fighter_b']
    html = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>'+escape(title)+'</title>',
        '<style>body{font:15px Segoe UI,Arial,sans-serif;max-width:1100px;margin:30px auto;padding:0 20px;color:#182230}table{border-collapse:collapse;width:100%;margin:12px 0 24px}th,td{padding:8px;border-bottom:1px solid #ddd;text-align:right}th:first-child,td:first-child{text-align:left}h2{font-size:18px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px Consolas,monospace}.note{color:#725200}@media print{body{margin:0}tr{break-inside:avoid}h2{break-after:avoid}}</style>',
        '<body><h1>'+escape(title)+'</h1><p>'+escape(str(payload['fight_date'])+' · '+str(payload.get('division','')))+'<br>'+escape(str(payload.get('generated_at','')))+' · '+escape(str(payload.get('result_state','complete')))+'</p>']
    for section in report_sections(payload):
        html += ['<h2>'+escape(section['title'])+'</h2><table><thead><tr><th>Metric</th><th>'+escape(payload['fighter_a'])+'</th><th>'+escape(payload['fighter_b'])+'</th><th>A−B</th></tr></thead><tbody>']
        for row in section['rows']:
            html.append('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in (row['label'],row['a'],row['b'],row['difference']))+'</tr>')
            if row['support_notes']:html.append('<tr><td colspan="4" class="note">'+escape('; '.join(row['support_notes']))+'</td></tr>')
        html.append('</tbody></table>')
    html += ['<h2>Complete report and model notes</h2><pre>'+escape(format_result(payload))+'</pre></body></html>']
    return '\n'.join(html)
