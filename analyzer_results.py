"""Detailed immutable report shared by the window, clipboard, TXT and CLI.

Use the engine's dated snapshots, never today's data joined into an old result.
"""
from __future__ import annotations
import math
import re
import textwrap

# label | engine field(s) | format. Percent fields are fractions, not percentages.
METRICS = '''PROFILE
Age (years)|age_at_fight|number
Height (cm)|height_cm|number
Reach (cm)|reach_cm|number
Reach / height|reach_height_ratio,reach_to_height_ratio|ratio
Stance|stance|text
ELO AND OPPONENT STRENGTH
Overall Elo|pre_elo,elo_before|number
Division Elo|pre_division_elo,division_elo_before|number
Recent Elo change|elo_recent_trend|number
Avg opponent Elo|avg_opponent_elo_before|number
All-history opponent Elo (refined)|avg_prior_opponent_elo_refined|number
Recent opponent Elo|recent_avg_opponent_elo|number
Strongest opponent faced (Elo)|best_prior_opponent_elo|number
Avg opponent pre-fight win rate (%)|prior_opponent_win_pct|percent
Last 3 opponent Elo|last_3_avg_opponent_elo_before|number
Avg opponent division Elo|avg_opponent_division_elo_before|number
Last 3 opponent division Elo|last_3_avg_opponent_division_elo_before|number
Best win opponent Elo|best_win_opponent_elo_before|number
Avg loss opponent Elo|avg_loss_opponent_elo_before|number
Highest loss opponent Elo|highest_loss_opponent_elo_before|number
UFC EXPERIENCE
UFC fights|ufc_fights_before|count
UFC wins|ufc_wins_before|count
UFC losses|ufc_losses_before|count
UFC draws|ufc_draws_before|count
UFC no contests|ufc_no_contests_before|count
UFC win rate (%)|ufc_win_pct_before|percent
UFC fight time (minutes)|career_minutes_before|number
Fights in selected division|fights_in_division_before|count
Division wins|division_wins_before|count
Division losses|division_losses_before|count
Division win rate (%)|division_win_pct_before|percent
Divisions competed in|num_divisions_before|count
Known five-round bouts|scheduled_five_round_fights_before|count
Late-round fights|late_round_fights_before|count
Five-round bouts|five_round_fight_count_before|count
Five-round fight time (minutes)|five_round_minutes_before|number
Five-round win rate (%)|five_round_win_pct_before|percent
Fights reaching round 3|round_3_plus_experience_before|count
Fights reaching round 4|round_4_plus_experience_before|count
Fights reaching round 5|round_5_experience_before|count
Decision experience (fights)|decision_experience|count
Previous division|prev_weight_class|text
Division movement|weight_class_movement|text
Changed division since last fight|changed_division_since_last_fight,changed_weight_class|flag
STRIKING
Sig. strikes landed / min|career_slpm_before|number
Sig. strikes absorbed / min|career_sapm_before|number
Sig. strike accuracy (%)|career_sig_str_accuracy_before|percent
Sig. strike defense (%)|career_sig_str_defense_before|percent
Total strike accuracy (%)|career_total_str_accuracy_before|percent
Total strike defense (%)|career_total_str_defense_before|percent
GRAPPLING
Takedowns landed / 15 min|career_td_avg_per15_before|number
Takedown accuracy (%)|career_td_accuracy_before|percent
Takedown defense (%)|career_td_defense_before|percent
Submission attempts / 15 min|career_sub_attempts_per15_before|number
Control seconds / 15 min|career_control_seconds_per15_before|number
Net control seconds / 15 min|career_control_diff_per15_before|number
RECENT FORM AND ACTIVITY
Current win streak|current_win_streak|count
Current loss streak|current_loss_streak|count
Days since last fight|days_since_last_fight|count
Days since last win|days_since_last_win,days_since_last_win_before|count
Days since last loss|days_since_last_loss,days_since_last_loss_before|count
Layoff category|layoff_bucket|text
Layoff longer than a year|long_layoff_flag|flag
Turnaround within 90 days|short_turnaround_flag|flag
Returning after a loss|returning_after_loss|flag
Last 3 win rate (%)|last_3_win_pct|percent
Last 3 net sig. strikes / min|last_3_sig_str_diff_per_min|number
Last 3 net takedowns / 15 min|last_3_td_diff_per15|number
Last 3 net control sec / 15 min|last_3_control_diff_per15|number
Last 5 win rate (%)|last_5_win_pct|percent
Last 5 net sig. strikes / min|last_5_sig_str_diff_per_min|number
Last 5 net takedowns / 15 min|last_5_td_diff_per15|number
Last 5 net control sec / 15 min|last_5_control_diff_per15|number
Fights in last 12 months|fights_last_12_months_before|count
Wins in last 12 months|wins_last_12_months_before|count
Losses in last 12 months|losses_last_12_months_before|count
Fights in last 24 months|fights_last_24_months_before|count
UFC WIN AND LOSS METHODS
Finish wins|finish_wins_before|count
KO/TKO wins|ko_tko_wins_before|count
Submission wins|submission_wins_before|count
Decision wins|decision_wins_before|count
Finish losses|finish_losses_before|count
KO/TKO losses|ko_tko_losses_before|count
Submission losses|submission_losses_before|count
Decision losses|decision_losses_before|count
Wins by finish (%)|finish_win_pct_before,finish_win_rate_before|percent
Wins by KO/TKO (%)|ko_tko_win_pct_before,ko_tko_win_rate_before|percent
Wins by submission (%)|submission_win_pct_before,sub_win_rate_before|percent
Wins by decision (%)|decision_win_pct_before,decision_win_rate_before|percent
Losses by finish (%)|finish_loss_pct_before,finish_loss_rate_before|percent
All decisive fights lost by finish (%)|been_finished_rate_before|percent
Late finishes / decisive fights (%)|late_finish_rate_before|percent
Method coverage (%)|method_coverage_before|percent
OPPONENT-ELO-WEIGHTED PERFORMANCE
Net sig. strikes / min (weighted)|opp_elo_weighted_sig_diff_per_min_before|number
Net takedowns / 15 min (weighted)|opp_elo_weighted_td_diff_per15_before|number
Net control sec / 15 min (weighted)|opp_elo_weighted_control_diff_per15_before|number
Last 3 net strikes / min (weighted)|last_3_opp_elo_weighted_sig_diff_per_min_before|number
Last 3 net TD / 15 min (weighted)|last_3_opp_elo_weighted_td_diff_per15_before|number
Last 3 net control sec / 15 (weighted)|last_3_opp_elo_weighted_control_diff_per15_before|number'''

def _text(value):
    return re.sub(r'[\x00-\x1f\x7f]', ' ', str(value)).strip()

def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):return None

def _value(value, unit, signed=False):
    if unit == 'text':return _text(value) if value is not None and _text(value) else 'N/A'
    number = _number(value)
    if number is None:return 'N/A'
    if unit == 'flag':return 'Yes' if number else 'No'
    if unit == 'percent':return f'{number*100:+.1f} pp' if signed else f'{number:.1%}'
    if unit == 'points':return f'{number*100:.1f} pp'
    precision = 0 if unit == 'count' else 3 if unit == 'ratio' else 2
    return format(number, ('+' if signed else '') + f'.{precision}f')

def _table(rows, columns):
    widths = [max(len(str(row[i])) for row in [columns] + rows) for i in range(len(columns))]
    def line(row):
        return ' | '.join(str(value).ljust(width) if i == 0 else str(value).rjust(width)
                          for i, (value, width) in enumerate(zip(row, widths)))
    return [line(columns), '-+-'.join('-'*width for width in widths)] + [line(row) for row in rows]

def _paragraph(text):
    return textwrap.wrap(_text(text), width=88, break_long_words=False, break_on_hyphens=False)

def _snapshots(payload):
    result = []
    for side in ('a', 'b'):
        summary = payload.get('feature_summary') or {}
        snapshot = dict(summary.get(f'fighter_{side}_snapshot') or {})
        snapshot.update(payload.get(f'fighter_{side}_snapshot') or {})
        snapshot.update(payload.get(f'fighter_{side}_comparison') or {})
        for name in ('elo_before', 'division_elo_before'):
            if snapshot.get(name) is None:snapshot[name] = summary.get(f'fighter_{side}_{name}')
        for row in payload.get('top_feature_differences', []):
            feature = row.get('feature', '')
            if feature.endswith('_diff'):
                base = feature[:-5]
                base = {'elo':'elo_before', 'division_elo':'division_elo_before', 'avg_opponent_elo':'avg_opponent_elo_before'}.get(base, base)
                if snapshot.get(base) is None:snapshot[base] = row.get(f'fighter_{side}_value')
        result.append(snapshot)
    return result

def _lookup(snapshot, fields):
    return next((snapshot[name] for name in fields.split(',') if snapshot.get(name) is not None), None)

def _comparison_row(label, fields, unit, snapshots):
    av, bv = [_lookup(snapshot, fields) for snapshot in snapshots]
    a, b = _number(av), _number(bv)
    difference = '—' if unit in ('text', 'flag') else _value(a-b, unit, True) if a is not None and b is not None else 'N/A'
    return [label, _value(av, unit), _value(bv, unit), difference]

def _bayes_metrics(snapshots, men):
    rows = []
    bases = [('Sig. strike accuracy', 'sig_str_acc', 'career_sig_str_accuracy_before'),
             ('Sig. strike defense', 'sig_str_def', 'career_sig_str_defense_before'),
             ('Total strike accuracy', 'total_str_acc', 'career_total_str_accuracy_before'),
             ('Total strike defense', 'total_str_def', 'career_total_str_defense_before'),
             ('Takedown accuracy', 'td_acc', 'career_td_accuracy_before'),
             ('Takedown defense', 'td_def', 'career_td_defense_before')]
    if men:
        for suffix, name in [('s20_women_style', 'prior strength 20'), ('s50_moderate', 'prior strength 50'),
                             ('current_men_v2_strength', 'men v2 prior'), ('support_scaled', 'support-scaled prior')]:
            for label, key, _ in bases:
                field = 'v3_bayes_'+key+'_'+suffix
                if any(field in snapshot for snapshot in snapshots):rows.append((label+' ('+name+')', field, 'percent'))
        for label, key, _ in bases:
            field = 'v3_bayes_'+key+'_denominator_before'
            if any(field in snapshot for snapshot in snapshots):rows.append((label+' support (attempts)', field, 'count'))
    else:
        for label, _, key in bases:
            if '_defense_' in key:
                key = key.replace('_defense_before', '_allowed_accuracy_before')
                label = label.replace('defense', 'opponent accuracy allowed')
            field = key+'_bayes_s20'
            if any(field in snapshot for snapshot in snapshots):rows.append((label+' (prior strength 20)', field, 'percent'))
            # Defense support is the opponents' attempts denominator.
            denominator = field+'_den_before'
            if any(denominator in snapshot for snapshot in snapshots):rows.append((label+' support (attempts)', denominator, 'count'))
    return rows

def _format_prediction(payload):
    title = payload['fighter_a'] + ' vs ' + payload['fighter_b']
    lines = ['UFC MATCHUP ANALYZER', title, '=' * min(len(title), 72), '',
             'Fight date: ' + str(payload['fight_date']),
             'Division: ' + str(payload.get('division', payload.get('weight_class', ''))), '',
             f"{payload['fighter_a']}: {payload['fighter_a_win_probability']:.1%}",
             f"{payload['fighter_b']}: {payload['fighter_b_win_probability']:.1%}", '',
             'Predicted winner: ' + payload['predicted_winner'],
             ('Confidence: ' if 'confidence_tier' in payload else 'Reliability: ') + str(payload.get('confidence_tier', payload.get('reliability_label', 'See model notes')))]
    if payload.get('reliability_score') is not None:lines[-1] += f" ({payload['reliability_score']}/100)"
    men = payload['model_version'].startswith('v3')
    snapshots = _snapshots(payload)
    comparison_columns = ['Metric', 'A: '+payload['fighter_a'], 'B: '+payload['fighter_b'], 'A - B']
    lines += ['', 'SIDE-BY-SIDE FIGHTER COMPARISON', 'A = '+payload['fighter_a'], 'B = '+payload['fighter_b']]
    lines += _paragraph('A - B is a numerical difference, not a score or guaranteed advantage. Percent differences use percentage points (pp). N/A means unavailable; 0 is a recorded or calculated zero.')
    from analyzer_reporting import report_sections
    for section in report_sections(payload):
        if section['title']=='BAYESIAN MODEL RATE ESTIMATES':continue
        lines += ['',section['title']]+_table([[r['label'],r['a'],r['b'],r['difference']] for r in section['rows']],comparison_columns)
    bayes = _bayes_metrics(snapshots, men)
    if bayes:
        lines += ['', 'BAYESIAN MODEL RATE ESTIMATES']
        lines += _paragraph('Smoothed estimates combine attempts with a prior to reduce instability in small samples. Support is the observed attempt denominator, not the number of fights. The report shows the rate variants supplied to the model; these are separate from raw career percentages.')
        lines += _table([_comparison_row(*row, snapshots) for row in bayes], comparison_columns)
    lines += ['', 'HOW TO READ THE COMPARISON']
    explanations = [
        'Elo is calculated from UFC results and opponent ratings, not official rankings. Overall and division ratings start at 1500. A division rating can remain at the baseline with little or no history in the selected division.',
        ('Avg opponent Elo uses up to the last five decisive fights for men; the refined all-history and recent opponent ratings use their own available-history windows.' if men else 'Avg opponent Elo averages the available prior UFC fight history. Best win opponent Elo is the strongest opponent defeated.'),
        'These are the retained engines\' UFC-history snapshots, which can differ from UFCStats profile averages. UFC win rate uses wins divided by wins plus losses, excluding draws and no contests. These statistics exclude non-UFC career fights. Win/loss method percentages use total wins/losses, respectively; missing method records can limit their coverage. Five-round win rate uses the engine\'s known five-round bout count.',
        'Fighter statistics use fights before the selected fight date. Model training uses the training filter shown below, which can be earlier with a CLI as-of date. Profile measurements can reflect later corrections.',
        'Net statistics are the fighter\'s output minus the opponents\' output. Lower absorbed-strike rates can be useful; a larger value is not always better. Recent form uses up to the last 3 or 5 available fights.',
    ]
    if not men:explanations += ['Elo-weighted performance averages per-fight differentials using opponent pre-fight Elo as weights. It is a comparison metric, not another win probability. Known five-round bouts can be a lower bound inferred from available bout-duration records.', 'Bayesian opponent accuracy allowed means the opponents\' success rate; lower is better. Raw defense means prevention of opponents\' attempts; higher is better.']
    for note in explanations:lines += _paragraph(note)+['']
    lines += ['MODEL DETAILS']
    components = [dict(row) for row in payload.get('model_predictions', []) if row.get('model') != 'ensemble_average']
    if not components:
        for model in ('gb_shallow_primary', 'cal_rf_sigmoid_challenger', 'logistic_c025_sanity'):
            field = model+'_fighter_a_win_probability'
            if field in payload:components.append(dict(model=model, fighter_a_win_probability=payload[field], fighter_b_win_probability=payload.get(model+'_fighter_b_win_probability'), direction_disagreement=payload.get(model+'_direction_disagreement')))
    if components:
        weights = payload.get('model_weights') or {}
        rows = [[row['model'], _value(row.get('fighter_a_win_probability'), 'percent'), _value(row.get('fighter_b_win_probability'), 'percent'), _value(row.get('direction_disagreement'), 'points'), _value(weights.get(row['model']), 'ratio')] for row in components]
        pa = payload.get('ensemble_probability')
        if pa is not None:rows.append(['Weighted ensemble', _value(pa, 'percent'), _value(1-pa, 'percent'), _value(payload.get('direction_disagreement'), 'points'), '—'])
        lines += _table(rows, ['Model', 'A win', 'B win', 'Direction gap', 'Weight'])
        lines += _paragraph('The current women\'s prediction uses the weighted ensemble. Direction gap measures disagreement between forward and reversed fighter order; smaller is more consistent. Weights are fractions summing to one.')
    elif payload.get('fighter_a_raw_avg_probability') is not None:
        pa = payload['fighter_a_raw_avg_probability']
        lines += _table([['Raw model (bidirectional)', _value(pa, 'percent'), _value(1-pa, 'percent')], ['Final calibrated prediction', _value(payload['fighter_a_win_probability'], 'percent'), _value(payload['fighter_b_win_probability'], 'percent')]], ['Probability', 'A win', 'B win'])
        if payload.get('shrink_factor') is not None:lines += _paragraph(f"Calibration shrink factor: {payload['shrink_factor']:.2f}. The final prediction moves the raw estimate toward 50% using the existing model policy.")
    used = payload.get('training_rows', payload.get('training_rows_used'))
    if used is not None:lines.append('Training rows used: '+str(used))
    if payload.get('training_unique_fights') is not None:lines.append('Unique training fights: '+str(payload['training_unique_fights']))
    cutoff = payload.get('actual_max_training_event_date_used') or payload.get('latest_training_event_date')
    lines += ['', 'Model: ' + str(payload['model_version'])]
    if cutoff:
        lines.append('Latest training fight used: ' + str(cutoff))
    lines.append('Training filter: '+str(payload.get('training_filter_cutoff') or ('event_date < '+payload['fight_date'])))
    rows = [[side.upper(), _value(snapshot.get('history_max_event_date_before'), 'text')] for side, snapshot in zip(('a', 'b'), snapshots) if 'history_max_event_date_before' in snapshot]
    if rows:lines += _table(rows, ['Fighter', 'Last fight included in snapshot'])
    lines += ['', 'RELIABILITY AND DATA QUALITY']
    if payload.get('reliability_meaning'):lines += _paragraph(payload['reliability_meaning'])
    if payload.get('model_vote'):lines.append('Model vote: '+payload['model_vote'])
    for label, field, unit in [('Model spread (A probability)', 'model_spread', 'points'), ('Forward/reverse disagreement', 'direction_disagreement', 'points'), ('Minimum UFC fights (either fighter)', 'min_ufc_fights', 'count'), ('Missing final model inputs', 'missing_final_feature_count', 'count')]:
        if field in payload:lines.append(label+': '+_value(payload[field], unit))
    factors = payload.get('reliability_factors') or []
    if factors:lines += _table([[_text(row.get('factor', '')), _text(row.get('status', '')), _text(row.get('effect', ''))] for row in factors], ['Factor', 'Status', 'Effect'])
    else:
        for label, field, denominator in [('Bayesian strike support', 'strike_support_level', 'strike_support_min_denominator'), ('Bayesian takedown support', 'td_support_level', 'td_support_min_denominator')]:
            if payload.get(field):lines.append(label+': '+str(payload[field])+' (minimum denominator '+_value(payload.get(denominator), 'count')+')')
    notes = list(payload.get('reliability_notes') or ([payload['reliability_note']] if payload.get('reliability_note') else []))
    warnings = list(payload.get('warnings') or [])+list(payload.get('manual_profile_warnings') or [])
    for note in dict.fromkeys(str(x) for x in notes+warnings):lines += _paragraph('• '+note)
    if not notes and not warnings:lines.append('No additional warnings reported; this does not guarantee data completeness.')
    if payload.get('elapsed_seconds') is not None:
        lines.append(f"Analysis time: {payload['elapsed_seconds']:.0f} seconds")
    lines += ['', 'Probabilities describe model estimates, not guaranteed outcomes.', 'Historical fight statistics exclude the selected fight date and later fights.']
    return '\n'.join(lines) + '\n'

def format_result(payload):
    from analyzer_reporting import report_sections
    state=payload.get('result_state','complete')
    if state=='complete':
        text=_format_prediction(payload)
    else:
        label='Statistics comparison — no prediction calculated.' if state=='comparison' else 'Comparison ready; prediction running.' if state=='pending' else 'Statistics comparison — prediction '+state+'. No completed prediction is available.'
        lines=['UFC MATCHUP ANALYZER',payload['fighter_a']+' vs '+payload['fighter_b'],'',label,
               'Fight date: '+str(payload['fight_date']),'Division: '+str(payload.get('division','')),'',
               'A−B is a numerical difference, not a guaranteed advantage. N/A means unavailable. Percentage differences use percentage points (pp).']
        columns=['Metric','A: '+payload['fighter_a'],'B: '+payload['fighter_b'],'A - B']
        for section in report_sections(payload):
            lines += ['',section['title']]+_table([[r['label'],r['a'],r['b'],r['difference']] for r in section['rows']],columns)
        lines += ['','Model algorithm: '+payload.get('model_version','Unknown'),
                  'Statistics use fights strictly before the selected date. Physical profile measurements may reflect later corrections.',
                  'Elo is an internal UFC-results rating starting at 1500, not an official ranking. Bayesian values combine dated observations with a prior.']
        for note in payload.get('warnings',[]):lines += _paragraph('• '+str(note))
        text='\n'.join(lines)+'\n'
    additions=[]
    for section in report_sections(payload):
        for row in section['rows']:
            additions.extend(row['label']+': '+note for note in row['support_notes'])
    additions.extend(payload.get('coverage_warnings',[]))
    if payload.get('history_notice'):additions.append(payload['history_notice'])
    if payload.get('generated_at'):additions.append('Generated: '+payload['generated_at'])
    if payload.get('reused'):additions.append('Reused saved analysis; original generation time shown above. Recalculate to run again.')
    return text+('\n'+'\n'.join(dict.fromkeys(additions))+'\n' if additions else '')

def result_filename(payload):
    name = payload['fighter_a'] + ' vs ' + payload['fighter_b']
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip().rstrip('. ')
    name = name[:180].rstrip('. ') or 'Matchup analysis'
    if name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        name = '_' + name
    return name + (' — statistics only' if payload.get('result_state','complete')!='complete' else '') + '.txt'
