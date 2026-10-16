"""Frozen coverage and methodology facts shared by every report surface."""
from __future__ import annotations
import math
from analyzer_history import fingerprint

SCHEMA = 1
LEGACY = 'Evidence-quality details were not recorded with this analysis.'
SUPPORT_LABELS = {
    'v3_bayes_'+key+'_denominator_before': label for key,label in (
        ('sig_str_acc','Significant strike accuracy'),('sig_str_def','Significant strike defense'),
        ('total_str_acc','Total strike accuracy'),('total_str_def','Total strike defense'),
        ('td_acc','Takedown accuracy'),('td_def','Takedown defense'))
}
SUPPORT_LABELS.update({
    'career_'+key+'_before_bayes_s20_den_before':label for key,label in (
        ('sig_str_accuracy','Significant strike accuracy'),('sig_str_allowed_accuracy','Opponent significant strike accuracy'),
        ('total_str_accuracy','Total strike accuracy'),('total_str_allowed_accuracy','Opponent total strike accuracy'),
        ('td_accuracy','Takedown accuracy'),('td_allowed_accuracy','Opponent takedown accuracy'))
})

def evaluation_status(report, context, sex):
    prefix = 'mens_ufc_model/' if sex == 'men' else 'womens_ufc_model/'
    datasets = {k:v for k,v in report.get('datasets',{}).items() if k.startswith(prefix)}
    code = {k:v for k,v in report.get('code',{}).items() if k.startswith(prefix)}
    model = report.get('models',{}).get(sex,{})
    audit = report.get('cv_audit',{}) if sex=='women' else model.get('methodology_audit',{})
    methodology = audit.get('status','NOT_ESTABLISHED')
    if not datasets or not code or not model:
        compatibility = 'unknown'
    elif model.get('model_version') != context.get('engine'):
        compatibility = 'different_model'
    elif any(context.get('code',{}).get(k)!=v for k,v in code.items()):
        compatibility = 'different_engine'
    elif any(context.get('datasets',{}).get(k)!=v for k,v in datasets.items()):
        compatibility = 'different_data'
    else:
        compatibility = 'matches'
    evaluated_methodology=methodology
    if compatibility in ('different_model','different_engine','unknown','unavailable'):methodology='NOT_ESTABLISHED'
    return dict(compatibility=compatibility,methodology=methodology,evaluated_methodology=evaluated_methodology,
        evaluation_status=report.get('status','UNKNOWN'),model_policy=context.get('engine'),
        evaluated_policy=model.get('model_version'),artifact_hash=report.get('integrity'),
        protocol_id=report.get('protocol_version'),holdout_bouts=sum(x.get('count',0) for x in model.get('calibration',[])),
        limitations=list(report.get('limitations',[])))

def build_evidence(payload, context, checks, report=None, report_error=None):
    request=payload.get('calculation_request',{})
    sex=request.get('sex') or ('women' if str(payload.get('model_version','')).startswith(('v1_current','v2_chronological')) else 'men')
    evaluation=evaluation_status(report,context,sex) if report else dict(compatibility='unavailable',methodology='NOT_ESTABLISHED',
        evaluation_status='UNAVAILABLE',model_policy=context.get('engine'),reason=report_error or 'No reviewed evaluation artifact')
    result=dict(schema=SCHEMA,scope=payload.get('result_state','initial'),generated_at=payload.get('generated_at'),
        fighter_a_id=payload.get('fighter_a_id'),fighter_b_id=payload.get('fighter_b_id'),
        division=payload.get('division'),history_cutoff=payload.get('fight_date'),
        training_cutoff=request.get('effective_cutoff') or payload.get('training_cutoff'),
        source_fingerprint=fingerprint(context.get('datasets',{})),
        data_through=max((c.get('latest_date') or '' for c in checks if c.get('status')=='PASS'),default='') or None,
        evaluation=evaluation,fighters={},metric_support=[])
    for side in ('a','b'):
        coverage=payload.get('coverage',{}).get(side,{})
        result['fighters'][side]=dict(name=payload.get('fighter_'+side),eligible_bouts=coverage.get('fights'),
            division_bouts=coverage.get('division_fights'),latest_bout=coverage.get('latest'),
            missing_reason=None if coverage else 'Coverage was not recorded')
    # Snapshot denominator fields are explicit attempt support, unlike coverage.
    for side in ('a','b'):
        snapshot=payload.get('fighter_'+side+'_comparison',{})
        for field,value in snapshot.items():
            if field not in SUPPORT_LABELS and ('bayes' not in field or not field.endswith('_den_before') or '_prior_' in field):continue
            if value is not None and isinstance(value,(int,float)):
                result['metric_support'].append(dict(side=side,metric_id=field,
                    label=SUPPORT_LABELS.get(field,'Smoothed rate'),attempts=value,status='prior_only' if value==0 else 'observed_attempts'))
        missing=snapshot.get('missing_profile_fields',[])
        if missing:result['fighters'][side]['missing_profile_fields']=list(missing)
    if not result['metric_support']:
        result['metric_support_reason']='Attempt denominators were not recorded with these statistics; recorded bout counts are a different measure of support.'
    return result

def validate_evidence(value):
    if not isinstance(value,dict) or value.get('schema')!=SCHEMA:
        raise ValueError('Unsupported evidence-quality schema')
    if not isinstance(value.get('fighters'),dict) or not isinstance(value.get('evaluation'),dict):
        raise ValueError('Invalid evidence-quality record')
    for side in ('a','b'):
        row=value['fighters'].get(side)
        if not isinstance(row,dict):raise ValueError('Missing fighter evidence')
        for field in ('eligible_bouts','division_bouts'):
            count=row.get(field)
            if count is not None and (type(count) is not int or count<0):raise ValueError('Invalid evidence bout count')
    if not isinstance(value.get('metric_support',[]),list):raise ValueError('Invalid metric support')
    for row in value.get('metric_support',[]):
        if not isinstance(row,dict) or row.get('side') not in ('a','b') or not isinstance(row.get('metric_id'),str):
            raise ValueError('Invalid metric support record')
        attempts=row.get('attempts')
        if type(attempts) not in (int,float) or attempts<0 or (type(attempts) is float and not math.isfinite(attempts)):
            raise ValueError('Invalid attempt count')
        expected='prior_only' if attempts==0 else 'observed_attempts'
        if row.get('status')!=expected:raise ValueError('Inconsistent attempt support')
        if 'label' in row and not isinstance(row['label'],str):raise ValueError('Invalid attempt support label')
    holdout=value['evaluation'].get('holdout_bouts')
    if holdout is not None and (type(holdout) is not int or holdout<0):
        raise ValueError('Invalid evaluation bout count')
    return value

def format_evidence(payload, compact=False):
    value=payload.get('evidence_quality')
    if value is None:return LEGACY
    validate_evidence(value)
    def count(v):return str(v) if v is not None else 'Unavailable'
    lines=[]
    for side in ('a','b'):
        row=value['fighters'][side]
        lines.append(str(row.get('name') or 'Fighter '+side.upper())+': '+count(row.get('eligible_bouts'))+
            ' eligible UFC bouts · '+count(row.get('division_bouts'))+' in selected division · latest '+str(row.get('latest_bout') or 'Unavailable'))
    evaluation=value['evaluation']
    compatibility={'matches':'Matches evaluated snapshot','different_model':'Model differs from evaluated policy',
        'different_engine':'Engine differs from evaluated source','different_data':'Data differs from evaluated snapshot',
        'unavailable':'Evaluation unavailable','unknown':'Evaluation provenance unavailable'}.get(evaluation.get('compatibility'),'Evaluation unavailable')
    methodology=evaluation.get('methodology')
    status=('Methodology audit failed' if methodology=='FAIL' else 'Methodology audit passed' if methodology=='PASS'
            else 'General validation not established')
    lines.append('Data through '+str(value.get('data_through') or 'Unavailable')+' · '+compatibility)
    if evaluation.get('evaluation_status')=='LIMITED_RETROSPECTIVE_EVALUATION':
        status+=' · Limited retrospective evidence (holdout n='+str(evaluation.get('holdout_bouts','Unavailable'))+')'
    lines.append(status)
    prior=sum(x.get('status')=='prior_only' for x in value.get('metric_support',[]))
    if prior:lines.append(str(prior)+' smoothed rates have no recorded supporting attempts; their estimates are prior-only.')
    if not compact:
        lines+=['History: event_date < '+str(value.get('history_cutoff') or 'Unknown'),
                'Training cutoff: '+str(value.get('training_cutoff') or 'Unknown'),
                'Recorded bouts can include draws/no-contests; attempt denominators describe individual rates.',
                'Evaluation: '+str(evaluation.get('evaluation_status','UNAVAILABLE')),
                'Model policy: '+str(evaluation.get('model_policy') or 'Unknown'),
                'Evaluated model policy: '+str(evaluation.get('evaluated_policy') or 'Unavailable'),
                'Evaluation protocol: '+str(evaluation.get('protocol_id') or 'Unavailable')]
        lines.extend(evaluation.get('limitations',[]))
        if evaluation.get('reason'):lines.append(evaluation['reason'])
        if value.get('metric_support_reason'):lines.append(value['metric_support_reason'])
        if value.get('metric_support'):
            lines.append('Observed attempt support (distinct from recorded bout counts):')
            for row in value['metric_support']:
                name=value['fighters'][row['side']].get('name') or 'Fighter '+row['side'].upper()
                attempts=str(row['attempts']) if type(row['attempts']) is int else format(row['attempts'],'g')
                lines.append(str(name)+' · '+row.get('label','Smoothed rate')+': '+attempts+
                    ' attempts'+(' · prior-only estimate' if row['status']=='prior_only' else ''))
        for row in value['fighters'].values():
            if row.get('missing_profile_fields'):lines.append(str(row['name'])+': unavailable profile fields: '+', '.join(row['missing_profile_fields']))
    return '\n'.join(lines)
