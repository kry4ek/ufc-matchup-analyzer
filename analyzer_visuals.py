"""Frozen paired bars and engine-derived pre-bout Elo evidence."""
from __future__ import annotations
import math
from html import escape
from analyzer_reporting import report_sections
from analyzer_results import _number, _value, _snapshots

LABELS=('Sig. strikes landed / min','Sig. strikes absorbed / min','Sig. strike accuracy (%)',
        'Takedowns landed / 15 min','Takedown defense (%)','Days since last fight')

def build_visual_evidence(payload, trends=None):
    bars=[]
    snapshots=_snapshots(payload)
    counts=[_number(s.get('ufc_fights_before')) for s in snapshots]
    coverage='Eligible engine history: A '+_value(counts[0],'count')+', B '+_value(counts[1],'count')+' fights. '
    for section in report_sections(payload):
        for row in section['rows']:
            if row['label'] not in LABELS: continue
            bars.append(dict(metric_id=row['fields'],semantic_version=1,label=row['label'],unit=row['unit'],
                             a=_number(row['raw_a']),b=_number(row['raw_b']),direction=row['direction'],
                             explanation=row['explanation'],support_notes=row['support_notes'],
                             support=coverage+('Attempt denominators unavailable for this legacy rate.' if '/' in row['label'] or row['unit']=='percent' else 'Recorded activity; not a performance rating.')))
    return dict(schema=1,history_cutoff=payload['fight_date'],bars=bars,
                elo=trends or {},elo_convention='Engine pre-bout ratings; men use stored decisive-bout states, women use the prepared live history. Points exclude the selected date. Same-day order is deterministic, not asserted bout chronology.')

def engine_trends(sex, prepared, payload):
    """Read existing engine states. No alternate Elo formula is calculated here."""
    result={}
    for side in ('a','b'):
        points=[]
        if sex=='women':
            rows=prepared['hist_stats']
            rows=rows[rows['fighter']==prepared['fighter_'+side]].sort_values(['event_date','fight_id'])
            for _,r in rows.iterrows():
                date=str(r['event_date'])[:10]
                if date>=payload['fight_date']: continue
                points.append(dict(date=date,fight_id=str(r['fight_id']),opponent=str(r.get('opponent','')),
                                   result=str(r.get('result','')),
                                   division=str(r.get('division','')),overall=_number(r.get('pre_elo')),
                                   division_elo=_number(r.get('pre_division_elo'))))
        else:
            # Stored pre-bout rows use the engine's canonical same-date Elo construction.
            # This is distinct from a newly calculated alternate rating series.
            import csv
            from pathlib import Path
            root=Path(__file__).resolve().parent
            wanted=payload.get('fighter_'+side+'_id') or getattr(prepared.get('fighter_'+side+'_result'), 'fighter_id',None)
            seen=set()
            with (root/'mens_ufc_model/data/processed/mens_training_rows_with_elo.csv').open(encoding='utf-8-sig',newline='') as stream:
                for row in csv.DictReader(stream):
                    if row['event_date'][:10]>=payload['fight_date'] or row['fight_id'] in seen: continue
                    prefix=next(('fighter_'+s+'_' for s in ('a','b') if row.get('fighter_'+s+'_id')==wanted),None)
                    if not prefix: continue
                    seen.add(row['fight_id']);other='fighter_b' if prefix=='fighter_a_' else 'fighter_a'
                    points.append(dict(date=row['event_date'][:10],fight_id=row['fight_id'],opponent=row.get(other,''),
                                       result=row.get(prefix+'result',''),
                                       division=row.get('weight_class',''),overall=_number(row.get(prefix+'elo_before')),
                                       division_elo=_number(row.get(prefix+'division_elo_before'))))
            points.sort(key=lambda r:(r['date'],r['fight_id']))
        result['fighter_'+side]=points
    return result

def evidence(payload):
    # Older records may supply bars from their own frozen metrics, never current datasets.
    return payload.get('visual_evidence') or build_visual_evidence(payload)

def format_visuals(payload):
    record=evidence(payload)
    if not record['bars'] and not record['elo']: return ''
    lines=['VISUAL EVIDENCE',record['elo_convention']]
    for row in record['bars']:
        lines.append(row['label']+': A '+_value(row['a'],row['unit'])+'; B '+_value(row['b'],row['unit'])+'. '+row['support'])
    for side in ('fighter_a','fighter_b'):
        lines.append(payload[side]+' — pre-bout Elo')
        points=record['elo'].get(side)
        if not points: lines.append('Elo trend was not saved or no eligible points are available.')
        for point in points or []:
            lines.append(point['date']+' | '+point['opponent']+' | '+str(point.get('result') or 'N/A')+' | '+point['division']+' | overall '+_value(point['overall'],'number')+' | division '+_value(point['division_elo'],'number'))
    return '\n'.join(lines)

def html_visuals(payload):
    record=evidence(payload)
    parts=['<section><h2>Visual comparison</h2>']
    for row in record['bars']:
        maximum=1 if row['unit']=='percent' else max([v for v in (row['a'],row['b']) if v is not None]+[1])
        parts.append('<h3>'+escape(row['label'])+'</h3><p>'+escape(row['support'])+'</p>')
        parts.append('<svg viewBox="0 0 640 76" role="img" aria-label="'+escape(row['label'],quote=True)+'">')
        for i,(side,color) in enumerate((('a','#286a9a'),('b','#a75c2a'))):
            value=row[side];y=8+i*32
            text=payload['fighter_'+side]+': '+_value(value,row['unit'])
            width=0 if value is None else max(0,min(330,value/maximum*330))
            parts.append(f'<rect x="300" y="{y}" width="{width:.2f}" height="22" fill="{color}"/><text x="0" y="{y+16}" font-size="14">'+escape(text)+'</text>')
        parts.append('</svg><p>Axis: 0–'+escape(_value(maximum,row['unit']))+'. '+escape(row['direction'])+'</p>')
    parts.append('<h3>Elo history</h3><p>'+escape(record['elo_convention'])+'</p>')
    for side,color in (('fighter_a','#286a9a'),('fighter_b','#a75c2a')):
        points=record['elo'].get(side,[]);parts.append('<h4>'+escape(payload[side])+'</h4>')
        vals=[p['overall'] for p in points if p['overall'] is not None]
        if vals:
            low=min(vals)-20;high=max(vals)+20
            coordinates=[]
            for i,p in enumerate(points):
                if p['overall'] is not None: coordinates.append(f'{40+i*540/max(1,len(points)-1):.2f},{170-(p["overall"]-low)/(high-low)*140:.2f}')
            parts.append('<svg viewBox="0 0 640 200" role="img" aria-label="Pre-bout Elo"><polyline fill="none" stroke="'+color+'" stroke-width="2" points="'+' '.join(coordinates)+'"/><text x="0" y="20">'+f'{high:.0f}'+'</text><text x="0" y="180">'+f'{low:.0f}'+'</text></svg><p>Horizontal axis: successive recorded bouts; table supplies dates.</p>')
        else: parts.append('<p>Elo trend was not saved or no eligible points are available.</p>')
        parts.append('<table><tr><th>Date</th><th>Opponent</th><th>Result</th><th>Division</th><th>Overall before</th><th>Division before</th></tr>')
        for p in points: parts.append('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in (p['date'],p['opponent'],p.get('result') or 'N/A',p['division'],_value(p['overall'],'number'),_value(p['division_elo'],'number')))+'</tr>')
        parts.append('</table>')
    return '\n'.join(parts+['</section>'])

class VisualPanel:
    def __init__(self,parent):
        import tkinter as tk
        from tkinter import ttk
        from tkinter.scrolledtext import ScrolledText
        parent.columnconfigure(0,weight=1);parent.rowconfigure(2,weight=1)
        bars=ttk.Frame(parent);bars.grid(row=0,column=0,sticky='ew');bars.columnconfigure(0,weight=1)
        self.canvas=tk.Canvas(bars,height=270,background='white',highlightthickness=0)
        self.canvas.grid(row=0,column=0,sticky='ew');self.canvas.bind('<Configure>',lambda event:self.draw())
        scrollbar=ttk.Scrollbar(bars,orient='vertical',command=self.canvas.yview)
        scrollbar.grid(row=0,column=1,sticky='ns');self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.bind('<MouseWheel>',lambda event:self.canvas.yview_scroll(-int(event.delta/120),'units'))
        self.trend=tk.Canvas(parent,height=165,background='white',highlightthickness=0)
        self.trend.grid(row=1,column=0,sticky='ew');self.trend.bind('<Configure>',lambda event:self.draw())
        self.table=ScrolledText(parent,height=7,wrap='word',font=('Segoe UI',10));self.table.grid(row=2,column=0,sticky='nsew')
        self.payload=None;self.points=10
    def show(self,payload):
        self.payload=payload;self.table.configure(state='normal');self.table.delete('1.0','end')
        self.table.insert('1.0',format_visuals(payload) or 'Visual evidence becomes available with the advanced comparison.')
        self.table.configure(state='disabled');self.canvas.yview_moveto(0);self.draw()
    def draw(self):
        self.canvas.delete('all');self.trend.delete('all')
        if not self.payload:return
        from tkinter import font as tkfont
        font=tkfont.Font(family='Segoe UI',size=self.points)
        axis_font=tkfont.Font(family='Segoe UI',size=8)
        line=max(15,font.metrics('linespace')+3);row_height=max(42,2*line+9)
        record=evidence(self.payload);width=max(500,self.canvas.winfo_width());start=width*.55
        axis_width=max([axis_font.measure('0–'+_value(1 if row['unit']=='percent' else max([v for v in (row['a'],row['b']) if v is not None]+[1]),row['unit'])) for row in record['bars']]+[55])
        span=max(1,width-start-axis_width-12)
        for i,row in enumerate(record['bars']):
            y=12+i*row_height;self.canvas.create_text(8,y,anchor='nw',text=row['label'],width=max(100,start-135),font=('Segoe UI',self.points))
            maximum=1 if row['unit']=='percent' else max([v for v in (row['a'],row['b']) if v is not None]+[1])
            for n,(side,color) in enumerate((('a','#286a9a'),('b','#a75c2a'))):
                value=row[side];bar=0 if value is None else max(0,min(span,value/maximum*span))
                self.canvas.create_rectangle(start,y+n*line,start+bar,y+n*line+line-5,fill=color,outline='')
                self.canvas.create_text(start-6,y+n*line+line/2,anchor='e',text=side.upper()+': '+_value(value,row['unit']),font=('Segoe UI',self.points))
            self.canvas.create_text(width-4,y+line/2,anchor='e',text='0–'+_value(maximum,row['unit']),font=('Segoe UI',8))
        self.canvas.configure(scrollregion=(0,0,width,24+len(record['bars'])*row_height))
        all_values=[p['overall'] for points in record['elo'].values() for p in points if p['overall'] is not None]
        if not all_values:
            self.trend.create_text(10,15,anchor='nw',text='No saved Elo trend. Numeric evidence and definitions appear below.');return
        low=min(all_values)-20;high=max(all_values)+20;w=max(500,self.trend.winfo_width())
        self.trend.create_text(8,6,anchor='nw',text=f'Pre-bout overall Elo ({low:.0f}–{high:.0f}); horizontal axis: successive bouts',font=('Segoe UI',8))
        self.trend.create_text(8,29,anchor='nw',text='A: '+self.payload['fighter_a']+'; B: '+self.payload['fighter_b'],font=('Segoe UI',8))
        count=max(len(points) for points in record['elo'].values())
        for side,color in (('fighter_a','#286a9a'),('fighter_b','#a75c2a')):
            points=record['elo'].get(side,[]);xy=[]
            for i,p in enumerate(points):
                if p['overall'] is None:continue
                x=45+i*(w-70)/max(1,count-1);y=145-(p['overall']-low)/(high-low)*85
                xy.extend((x,y));self.trend.create_oval(x-2,y-2,x+2,y+2,fill=color,outline=color)
            if len(xy)>=4:self.trend.create_line(*xy,fill=color,width=2)
