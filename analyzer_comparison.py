"""Compare immutable saved analyses without recalculation or guessed identities."""
from __future__ import annotations
import copy
import math
from html import escape

def compare_entries(original, newer):
    left,right = copy.deepcopy(original),copy.deepcopy(newer)
    a,b = left['payload'],right['payload']
    if left['request']['sex'] != right['request']['sex']: raise ValueError('Choose two analyses from the same model family.')
    ids_a = [a.get('fighter_'+s+'_id') for s in ('a','b')]
    ids_b = [b.get('fighter_'+s+'_id') for s in ('a','b')]
    if not all(ids_a+ids_b) or len(set(ids_a)) != 2 or set(ids_a)!=set(ids_b):
        raise ValueError('The reports must identify the same two fighters by stable IDs.')
    reversed_sides = ids_a != ids_b
    context_changes = []
    for field in ('division','fight_date','model_version','worker_mode','actual_max_training_event_date_used'):
        if a.get(field)!=b.get(field): context_changes.append(dict(field=field,before=a.get(field),after=b.get(field)))
    for field in ('datasets','code','dependencies','python','engine','report_version','validation_artifact_sha256'):
        if left['context'].get(field)!=right['context'].get(field):
            context_changes.append(dict(field=field,before=left['context'].get(field),after=right['context'].get(field)))
    for field in ('as_of_date','effective_cutoff','workers','profiles_sha256'):
        if left['request'].get(field)!=right['request'].get(field):
            context_changes.append(dict(field=field,before=left['request'].get(field),after=right['request'].get(field)))
    probability = []
    if a.get('result_state','complete')=='complete' and b.get('result_state','complete')=='complete':
        for side, other in (('a','b' if reversed_sides else 'a'),('b','a' if reversed_sides else 'b')):
            x,y=a.get('fighter_'+side+'_win_probability'),b.get('fighter_'+other+'_win_probability')
            if isinstance(x,(int,float)) and isinstance(y,(int,float)):
                probability.append(dict(fighter=a['fighter_'+side],before=x,after=y,delta_pp=(y-x)*100))
    metrics = []
    coverage_changes=[]
    for side,other in (('a','b' if reversed_sides else 'a'),('b','a' if reversed_sides else 'b')):
        x=a.get('coverage',{}).get(side);y=b.get('coverage',{}).get(other)
        if x!=y:coverage_changes.append(dict(fighter=a['fighter_'+side],before=x,after=y))
    # Legacy reports lack a frozen semantic contract. Do not silently assume equivalence.
    ar=a.get('metric_records');br=b.get('metric_records')
    if ar and br:
        before_lookup={r['id']:r for r in ar}
        lookup={r['id']:r for r in br}
        for metric_id in dict.fromkeys([r['id'] for r in ar]+[r['id'] for r in br]):
            previous=before_lookup.get(metric_id);s=lookup.get(metric_id);r=previous or s
            compatible=previous and s and all(previous.get(k)==s.get(k) for k in ('semantic_version','unit','window'))
            for side,other in (('a','b' if reversed_sides else 'a'),('b','a' if reversed_sides else 'b')):
                x=previous.get('raw_'+side) if previous else None;y=s.get('raw_'+other) if s else None
                delta=None
                if compatible and isinstance(x,(int,float)) and isinstance(y,(int,float)) and all(map(math.isfinite,(x,y))):delta=(y-x)*(100 if r['unit']=='percent' else 1)
                if x!=y or not compatible:
                    metrics.append(dict(metric_id=r['id'],label=r['label'],fighter=a['fighter_'+side],before=x,after=y,delta=delta,
                                        unit=r['unit'],status='compatible' if compatible else 'Definition changed or unavailable'))
    fights=[];evidence_a=a.get('fight_evidence');evidence_b=b.get('fight_evidence')
    if evidence_a and evidence_b:
        for side,other in (('a','b' if reversed_sides else 'a'),('b','a' if reversed_sides else 'b')):
            old={r['fight_id']:r for r in evidence_a['fighter_'+side]};new={r['fight_id']:r for r in evidence_b['fighter_'+other]}
            for fid in sorted(set(old)|set(new)):
                if old.get(fid)!=new.get(fid):
                    fights.append(dict(fighter=a['fighter_'+side],fight_id=fid,change='newly eligible' if fid not in old else 'no longer eligible' if fid not in new else 'record changed',before=old.get(fid),after=new.get(fid)))
    limitations=[]
    recent_changes=[]
    if a.get('recent_form') and b.get('recent_form'):
        for side,other in (('a','b' if reversed_sides else 'a'),('b','a' if reversed_sides else 'b')):
            for window in ('3','5','career'):
                old=a['recent_form']['fighter_'+side]['windows'][window]
                new=b['recent_form']['fighter_'+other]['windows'][window]
                for x,y in zip(old['metrics'],new['metrics']):
                    if x!=y:
                        compatible=all(x.get(k)==y.get(k) for k in ('id','semantic_version','unit'))
                        delta=(y['value']-x['value'])*(100 if x['unit']=='percent' else 1) if compatible and x['value'] is not None and y['value'] is not None else None
                        recent_changes.append(dict(fighter=a['fighter_'+side],window=window,label=x['label'],before=x,after=y,delta=delta))
    else:limitations.append('Recent-form evidence was not captured in both reports; recent-form changes are unavailable.')
    if not ar or not br:limitations.append('Compatible metric definitions were not saved in both reports; metric deltas are unavailable.')
    if not evidence_a or not evidence_b:limitations.append('Full eligible-fight evidence was not saved in both reports; fight changes are unavailable.')
    if not probability:limitations.append('Probability comparison requires two completed predictions.')
    if context_changes:limitations.append('Changed inputs are shown; this comparison does not attribute a probability shift to any single cause.')
    if a.get('fight_date')!=b.get('fight_date'):
        limitations.append('The matchup date changed. Newly/no longer eligible bouts reflect cutoff changes; record-changed entries describe source differences for shared bouts.')
    if not left.get('context') or not right.get('context'):limitations.append('Full saved calculation provenance is unavailable for a transient report.')
    return dict(schema=1,original=left,newer=right,reversed_sides=reversed_sides,context_changes=context_changes,
                probability=probability,metrics=metrics,fights=fights,coverage_changes=coverage_changes,limitations=limitations,recent_changes=recent_changes)

def format_comparison(value):
    a,b=value['original']['payload'],value['newer']['payload']
    lines=['SAVED ANALYSIS COMPARISON',a['fighter_a']+' vs '+a['fighter_b'],
           'Original: '+str(a.get('generated_at','Unknown'))+' / '+str(a.get('division','Unavailable'))+' / fight date '+a['fight_date'],
           'Newer: '+str(b.get('generated_at','Unknown'))+' / '+str(b.get('division','Unavailable'))+' / fight date '+b['fight_date']]
    if value['reversed_sides']:lines.append('Newer fighter order aligned to the original report.')
    if value['probability']:
        lines+=['','PROBABILITIES — before → after']
        for r in value['probability']:lines.append(f"{r['fighter']}: {r['before']:.1%} → {r['after']:.1%}; {r['delta_pp']:+.2f} pp")
    if not any(r['delta_pp'] for r in value['probability']) and not any(value[k] for k in ('metrics','fights','coverage_changes')) and not value.get('recent_changes'):
        lines+=['','No material result changes. Generation times can differ; calculation-context changes appear below.']
    lines += ['','CONTEXT CHANGES']
    for row in value['context_changes']:
        if row['field'] in ('datasets','code','dependencies'):
            lines.append(row['field']+':')
            old,new=row['before'] or {},row['after'] or {}
            for name in sorted(set(old)|set(new)):
                if old.get(name)!=new.get(name):lines.append('  '+name+': '+str(old.get(name,'Unavailable'))+' → '+str(new.get(name,'Unavailable')))
        else:lines.append(row['field']+': '+str(row['before'])+' → '+str(row['after']))
    lines += ['','METRIC CHANGES']
    for r in value['metrics']:
        delta='N/A' if r['delta'] is None else f"{r['delta']:+.4g}"+(' pp' if r['unit']=='percent' else '')
        lines.append(f"{r['fighter']} / {r['label']}: {r['before']} → {r['after']}; delta {delta}; {r['status']}")
    lines += ['','ELIGIBLE FIGHT CHANGES']
    for r in value['fights']:
        lines.append(r['fighter']+' / '+r['fight_id']+': '+r['change'])
        for label in ('before','after'):
            record=r[label]
            lines.append('  '+label+': '+('Unavailable' if record is None else '; '.join(str(k)+'='+str(v) for k,v in record.items())))
    lines += ['','COVERAGE CHANGES']
    for r in value.get('coverage_changes',[]):lines.append(r['fighter']+': '+str(r['before'])+' → '+str(r['after']))
    lines+=['','RECENT FORM CHANGES']
    for r in value.get('recent_changes',[]):
        lines.append(r['fighter']+' / '+r['window']+' / '+r['label']+': '+str(r['before']['value'])+' → '+str(r['after']['value'])+'; delta '+str(r['delta'])+(' pp' if r['before']['unit']=='percent' else '')+'; support '+str(r['before']['eligible_bouts'])+' → '+str(r['after']['eligible_bouts'])+' bouts')
    return '\n'.join(lines+['','LIMITATIONS']+value['limitations'])+'\n'

def comparison_html(value):
    return '<!doctype html><html lang="en"><meta charset="utf-8"><title>Saved analysis comparison</title><style>body{font:16px Segoe UI,sans-serif;max-width:1000px;margin:24px auto;padding:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><body><pre>'+escape(format_comparison(value))+'</pre></body></html>'
