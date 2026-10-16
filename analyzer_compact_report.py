"""Self-contained printable summary of one frozen report."""
from html import escape
from analyzer_bout_context import form_rows, UNRECORDED, results_text

KEY_COMPARISONS=('Reach (cm)','Overall Elo','Sig. strikes landed / min','Sig. strikes absorbed / min',
                 'Takedowns landed / 15 min','Takedown defense (%)')

def compact_html(payload,window='5'):
    if str(window) not in ('3','5'):raise ValueError('Choose Last 3 or Last 5')
    from analyzer_reporting import overview_rows
    from analyzer_evidence import format_evidence
    from analyzer_fight_history import display_row
    e=lambda v:escape(str(v))
    state=payload.get('result_state','complete')
    title=payload['fighter_a']+' vs '+payload['fighter_b']
    html=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>'+e(title)+' — compact</title>',
        '''<style>@page{size:auto;margin:12mm}*{box-sizing:border-box}body{font:13px/1.3 "Segoe UI",Arial,sans-serif;color:#182230;margin:20px auto;max-width:980px;padding:0 14px}h1{font-size:23px;margin:0 0 6px;overflow-wrap:anywhere}h2{font-size:15px;margin:12px 0 5px;break-after:avoid}h3{font-size:13px;margin:8px 0 3px}.meta,.note{font-size:11px;overflow-wrap:anywhere}.prediction{display:flex;gap:16px;margin:10px 0;font-size:22px;font-weight:600}.prediction>div{flex:1;overflow-wrap:anywhere}table{width:100%;border-collapse:collapse;table-layout:fixed}th,td{padding:4px 5px;border-bottom:1px solid #cbd3df;text-align:right;overflow-wrap:anywhere;vertical-align:top}th:first-child,td:first-child{text-align:left;width:36%}tr{break-inside:avoid}thead{display:table-header-group}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}.evidence{white-space:pre-line;font-size:11px;background:#f2f5f9;padding:8px}footer{font-size:10px;border-top:1px solid #aeb9c9;margin-top:10px;padding-top:5px}@media(max-width:650px){.pair{grid-template-columns:1fr}.prediction{font-size:18px}}@media print{body{font-size:9pt;line-height:1.18;margin:0;max-width:none;padding:0}h1{font-size:16pt}h2{font-size:10pt;margin-top:7px}h3{font-size:9pt}th,td{padding:3px 4px}.meta,.note,.evidence{font-size:8pt}.prediction{font-size:16pt;margin:6px 0}.pair{display:grid;grid-template-columns:1fr 1fr;gap:10px}footer{font-size:7.5pt}.evidence{background:none;padding:4px;border:1px solid #cbd3df}}</style>''',
        '<body><h1>'+e(title)+'</h1><p class="meta">'+e(payload.get('division',''))+' · Fight date '+e(payload['fight_date'])+' · '+e(state)+
        '<br>Generated '+e(payload.get('generated_at','Unavailable'))+'</p>']
    if state=='complete' and not payload.get('quick_comparison'):
        html.append('<div class="prediction">'+''.join('<div>'+e(payload['fighter_'+s])+': '+e(f"{payload['fighter_'+s+'_win_probability']:.1%}")+'</div>' for s in ('a','b'))+'</div>')
        html.append('<p class="meta">'+('Recorded confidence tier: ' if 'confidence_tier' in payload else 'Recorded reliability: ')+e(payload.get('confidence_tier',payload.get('reliability_label','Unavailable')))+' · not outcome certainty.</p>')
    else:html.append('<p><strong>'+e('Partial evidence' if payload.get('quick_comparison') else state.title())+' — no completed prediction.</strong></p>')
    html+=['<div class="evidence">'+e(format_evidence(payload,compact=True))+'</div>',
        '<h2>Key model comparisons</h2><table><thead><tr><th>Metric</th><th>'+e(payload['fighter_a'])+'</th><th>'+e(payload['fighter_b'])+'</th><th>A − B</th></tr></thead><tbody>']
    lookup={r['label']:r for r in overview_rows(payload)}
    for label in KEY_COMPARISONS:
        row=lookup[label];html.append('<tr>'+''.join('<td>'+e(row[k])+'</td>' for k in ('label','a','b','difference'))+'</tr>')
    html+=['</tbody></table>',f'<h2>Last {window} versus UFC career</h2><p class="note">All recorded UFC divisions; career includes the recent window. These descriptive rates pool recorded totals without model priors. Recent / career support appears beneath each fighter.</p><div class="pair">']
    for side in ('fighter_a','fighter_b'):
        rows=form_rows(payload,side,window)
        html+=['<section><h3>'+e(payload[side])+'</h3>']
        if not rows:html.append('<p class="note">'+e(UNRECORDED)+'</p>')
        else:
            data=payload['recent_form'][side]['windows'];recent=data[str(window)];career=data['career']
            html.append(f'<p class="note">Actual recent bouts: {recent["bout_count"]}; career: {career["bout_count"]}.<br>Recent results: '+e(results_text(recent['results']))+'</p>')
            html.append('<table><thead><tr><th>Metric</th><th>Recent</th><th>Career</th></tr></thead><tbody>')
            for row in (rows[0],rows[2],rows[3]):html.append('<tr>'+''.join('<td>'+e(x)+'</td>' for x in row[:3])+'</tr><tr><td colspan="3" class="note">'+e(row[4])+'</td></tr>')
            html.append('</tbody></table>')
        html.append('</section>')
    html+=['</div><h2>Three most recent recorded UFC bouts per fighter</h2><div class="pair">']
    history=payload.get('recent_fights',{})
    for side in ('fighter_a','fighter_b'):
        html.append('<section><h3>'+e(payload[side])+'</h3>')
        for bout in history.get(side,[])[:3]:html.append('<p class="note">'+e(' · '.join(display_row(bout)))+'</p>')
        if not history.get(side):html.append('<p class="note">No captured recent bouts.</p>')
        html.append('</section>')
    evidence=payload.get('evidence_quality',{})
    warnings=list(dict.fromkeys(payload.get('coverage_warnings',[])+payload.get('warnings',[])))
    limitations=evidence.get('evaluation',{}).get('limitations',[])
    html+=['</div><footer>Experimental estimates; outcomes are uncertain. A − B is a numerical difference. Percent differences use percentage points. '+
        'History excludes the selected date; source/profile corrections may be newer. Training cutoff: '+e(evidence.get('training_cutoff','Unavailable'))+
        '. Model: '+e(payload.get('model_version','Unavailable'))+'; app '+e(payload.get('analyzer_version','Unavailable'))+'.<br>'+e(' '.join(warnings+limitations))+
        '<br>Compact subset; consult the detailed report for all metrics, bout details and methodology. Print at 100% on A4/Letter with browser headers/footers off. Long necessary notes may use a second page.</footer></body></html>']
    return '\n'.join(html)
