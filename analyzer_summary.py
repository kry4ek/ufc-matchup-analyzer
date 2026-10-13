"""Deterministic observations backed by frozen structured comparison metrics."""
from __future__ import annotations
import math
from analyzer_reporting import report_sections

SCHEMA = 1
OLD_MESSAGE = 'A matchup summary was not saved with this analysis.'
# Thresholds are presentation rules, not significance tests or confidence grades.
RULES = (
    ('UFC fights', 3, 0, 'Recorded UFC experience'),
    ('Days since last fight', 60, 0, 'Days since last recorded fight'),
    ('Overall Elo', 100, 5, 'Internal results rating'),
    ('Avg opponent Elo', 100, 5, 'Recorded opponent strength'),
    ('Sig. strikes landed / min', 1, 5, 'Recorded striking output'),
    ('Takedowns landed / 15 min', 1, 5, 'Recorded takedown output'),
)

def metric_records(payload):
    return [dict(id=r['fields'], semantic_version=1, window='engine-defined history before selected date',
                 **{k:r[k] for k in ('label','unit','raw_a','raw_b','raw_difference','support_notes','explanation')})
            for section in report_sections(payload) for r in section['rows']]

def build_summary(payload):
    rows = {r['label']:r for r in metric_records(payload)}
    observations = []
    limitations = []
    coverage = payload.get('coverage', {})
    for label, threshold, minimum, title in RULES:
        row = rows.get(label)
        if not row: continue
        values = [row['raw_a'],row['raw_b']]
        try:
            a,b = map(float,values)
            if not all(map(math.isfinite,(a,b))) or abs(a-b) < threshold: continue
        except (TypeError,ValueError): continue
        if minimum and any(coverage.get(side,{}).get('fights',0) < minimum for side in ('a','b')): continue
        if row['support_notes']: continue
        # Rate observations require recorded denominators, not merely a fight count.
        if '/ min' in label or '/ 15 min' in label:
            continue  # Support for these legacy rates is not exposed consistently by both engines.
        unit = 'days' if label=='Days since last fight' else 'fights' if label=='UFC fights' else 'rating points'
        text = f"{title}: {payload['fighter_a']} {a:g}, {payload['fighter_b']} {b:g} ({unit})."
        observations.append(dict(metric_id=row['id'],text=text,evidence=row))
        if len(observations)==3: break
    for warning in payload.get('coverage_warnings',[]):
        if warning not in limitations: limitations.append(warning)
    for row in rows.values():
        for note in row['support_notes']:
            if note not in limitations: limitations.append(note)
    if len(observations)<3:
        for label in ('Sig. strike accuracy','Takedown accuracy','Takedown defense'):
            rate=next((r for name,r in rows.items() if name.startswith(label+' (prior strength 20)')),None)
            support=rows.get(label+' support (attempts)')
            if not rate or not support:continue
            try:
                a,b=map(float,(rate['raw_a'],rate['raw_b']));sa,sb=map(float,(support['raw_a'],support['raw_b']))
                if not all(map(math.isfinite,(a,b,sa,sb))) or min(sa,sb)<20 or abs(a-b)<.10:continue
            except (ValueError,TypeError):continue
            observations.append(dict(metric_id=rate['id'],text=f"Smoothed {label.casefold()}: {payload['fighter_a']} {a:.1%}, {payload['fighter_b']} {b:.1%} (support: {sa:g}/{sb:g} attempts).",evidence=rate,support=support))
            if len(observations)==3:break
    if not observations:
        observations.append(dict(metric_id=None,text='The available evidence does not support a distinct summary under these rules.',evidence=None))
    return dict(schema=SCHEMA,rules_version=1,observations=observations,limitations=limitations[:2],
                note='Statistical observations; these do not explain the model probability. History uses the installed source, including later corrections.')

def format_summary(payload):
    summary = payload.get('matchup_summary')
    if not summary: return OLD_MESSAGE
    return '\n'.join([x['text'] for x in summary['observations']] + summary['limitations'] + [summary['note']])
