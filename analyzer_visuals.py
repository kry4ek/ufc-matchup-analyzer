"""Frozen paired bars and engine-derived pre-bout Elo evidence."""
from __future__ import annotations
import math
from html import escape
from analyzer_theme import COLORS
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
                                   opponent_overall=_number(r.get('opponent_elo_before')),
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
                                       opponent_overall=_number(row.get(other+'_elo_before')),
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
        for index,point in enumerate(points or [],1):
            lines.append('Bout '+str(index)+' | '+point['date']+' | '+point['opponent']+' | '+str(point.get('result') or 'N/A')+' | '+point['division']+' | overall '+_value(point['overall'],'number')+' | division '+_value(point['division_elo'],'number'))
    return '\n'.join(lines)

def html_visuals(payload):
    record=evidence(payload)
    parts=['<section><h2>Charts</h2><p>'+escape('A: '+payload['fighter_a']+' · B: '+payload['fighter_b'])+'</p>']
    for row in record['bars']:
        maximum=1 if row['unit']=='percent' else max([v for v in (row['a'],row['b']) if v is not None]+[1])
        parts.append('<h3>'+escape(row['label'])+'</h3><p>'+escape(row['support'])+'</p>')
        parts.append('<svg viewBox="0 0 640 76" role="img" aria-label="'+escape(row['label'],quote=True)+'">')
        for i,(side,color) in enumerate((('a',COLORS['fighter_a']),('b',COLORS['fighter_b']))):
            value=row[side];y=8+i*32
            text=side.upper()+': '+_value(value,row['unit'])
            width=0 if value is None else max(0,min(500,value/maximum*500))
            parts.append(f'<rect x="120" y="{y}" width="{width:.2f}" height="22" fill="{color}"/><text x="0" y="{y+16}" font-size="14">'+escape(text)+'</text>')
        parts.append('</svg><p>Axis: 0–'+escape(_value(maximum,row['unit']))+'. '+escape(row['direction'])+'</p>')
    parts.append('<h3>Elo history</h3><p>'+escape(record['elo_convention'])+'</p>')
    for side,color in (('fighter_a',COLORS['fighter_a']),('fighter_b',COLORS['fighter_b'])):
        points=record['elo'].get(side,[]);parts.append('<h4>'+escape(payload[side])+'</h4>')
        vals=[p['overall'] for p in points if p['overall'] is not None]
        if vals:
            low=min(vals)-20;high=max(vals)+20
            coordinates=[];segments=[[]]
            for i,p in enumerate(points):
                if p['overall'] is None:
                    if segments[-1]:segments.append([])
                    continue
                xy=f'{40+i*540/max(1,len(points)-1):.2f},{170-(p["overall"]-low)/(high-low)*140:.2f}'
                coordinates.append(xy);segments[-1].append(xy)
            markers=''.join('<circle cx="'+xy.split(',')[0]+'" cy="'+xy.split(',')[1]+'" r="3" fill="'+color+'"/>' for xy in coordinates)
            lines=''.join('<polyline fill="none" stroke="'+color+'" stroke-width="2" points="'+' '.join(segment)+'"/>' for segment in segments if len(segment)>1)
            grid=''.join(f'<line x1="40" x2="580" y1="{y}" y2="{y}" stroke="{COLORS["border"]}"/>' for y in (30,100,170))
            parts.append('<svg viewBox="0 0 640 200" role="img" aria-label="Pre-bout Elo">'+grid+lines+markers+'<text x="0" y="20">'+f'{high:.0f}'+'</text><text x="0" y="180">'+f'{low:.0f}'+'</text><text x="40" y="198">Bout 1</text><text x="520" y="198">Bout '+str(len(points))+'</text></svg><p>Horizontal axis: successive recorded bouts; table supplies dates.</p>')
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
        from analyzer_presentation import ScrollPanel
        parent.columnconfigure(0,weight=1);parent.rowconfigure(1,weight=1)
        legend=ttk.Frame(parent);legend.grid(row=0,column=0,sticky='ew',pady=(0,8));legend.columnconfigure(0,weight=1);legend.columnconfigure(1,weight=1)
        self.legend=[]
        for column,side in enumerate(('a','b')):
            label=ttk.Label(legend,text='Fighter '+side.upper(),foreground=COLORS['fighter_'+side],wraplength=350)
            label.grid(row=0,column=column,sticky='nw',padx=(0,16));self.legend.append(label)
        self.scroll=ScrollPanel(parent);self.scroll.grid(row=1,column=0,sticky='nsew')
        content=self.scroll.content
        self.canvas=tk.Canvas(content,height=500,background='white',highlightthickness=0)
        self.canvas.grid(row=0,column=0,sticky='ew');self.canvas.bind('<Configure>',lambda event:self.draw())
        ttk.Label(content,text='Pre-bout overall Elo',style='Section.TLabel').grid(row=1,column=0,sticky='w',pady=(20,4))
        self.elo_legend=ttk.Label(content,text='',style='Caption.TLabel',wraplength=700)
        self.elo_legend.grid(row=2,column=0,sticky='w')
        self.trend=tk.Canvas(content,height=260,background='white',highlightthickness=2,highlightbackground=COLORS['surface'],highlightcolor=COLORS['primary'],takefocus=True)
        self.trend.grid(row=3,column=0,sticky='ew');self.trend.bind('<Configure>',lambda event:self.draw())
        self.inspection=tk.StringVar(value='Point details are also available in the selectable numeric evidence below.')
        self.inspection_label=ttk.Label(content,textvariable=self.inspection,style='Caption.TLabel',wraplength=700)
        self.inspection_label.grid(row=4,column=0,sticky='ew',pady=(4,12))
        ttk.Label(content,text='Numeric evidence and definitions',style='Section.TLabel').grid(row=5,column=0,sticky='w',pady=(12,8))
        self.table=ScrolledText(content,height=10,wrap='word',font=('Segoe UI',10),background='white',foreground=COLORS['text'],padx=8,pady=8)
        self.table.grid(row=6,column=0,sticky='ew')
        self.payload=None;self.points=10;self.point_positions=[];self.selected_point=0
        self.scroll.bind_children()
        # Preserve independent scrolling inside the full numeric evidence.
        self.table.bind('<MouseWheel>',lambda e:self.table.yview_scroll(-int(e.delta/120),'units') or 'break')
        self.trend.bind('<Motion>',self.inspect_point)
        self.trend.bind('<Left>',lambda e:self.step_point(-1));self.trend.bind('<Right>',lambda e:self.step_point(1))

    def show(self,payload,render=True):
        self.payload=payload;self.table.configure(state='normal');self.table.delete('1.0','end')
        self.table.insert('1.0',format_visuals(payload) or 'Visual evidence becomes available with the advanced comparison.')
        self.table.configure(state='disabled');self.scroll.canvas.yview_moveto(0);self.selected_point=0
        self.inspection.set('Use Left/Right on the Elo chart to inspect points; the numeric evidence below also lists every point.')
        for label,side in zip(self.legend,('a','b')):label.configure(text=side.upper()+': '+payload['fighter_'+side])
        self.elo_legend.configure(text='A: '+payload['fighter_a']+' · B: '+payload['fighter_b'])
        self.dirty=not render
        if render:self.draw()

    def point_text(self,point):
        side,index,p,x,y=point
        return self.payload[side]+' · Bout '+str(index+1)+' · '+str(p.get('date') or 'Date not recorded')+' · Overall Elo '+_value(p.get('overall'),'number')+' · '+str(p.get('opponent') or 'Opponent not recorded')

    def inspect_point(self,event):
        if not self.point_positions:return
        point=min(self.point_positions,key=lambda p:(p[3]-event.x)**2+(p[4]-event.y)**2)
        if (point[3]-event.x)**2+(point[4]-event.y)**2<225:self.inspection.set(self.point_text(point))

    def step_point(self,delta):
        if self.point_positions:
            self.selected_point=max(0,min(len(self.point_positions)-1,self.selected_point+delta))
            self.inspection.set(self.point_text(self.point_positions[self.selected_point]));self.mark_selected()
        return 'break'

    def mark_selected(self):
        self.trend.delete('selected')
        if self.point_positions:
            point=self.point_positions[min(self.selected_point,len(self.point_positions)-1)];x,y=point[3:]
            self.trend.create_oval(x-5,y-5,x+5,y+5,outline=COLORS['text'],width=2,tags='selected')

    def draw(self):
        self.canvas.delete('all');self.trend.delete('all');self.point_positions=[]
        from tkinter import font as tkfont
        font=tkfont.Font(family='Segoe UI',size=self.points)
        line=font.metrics('linespace')+5
        width=max(200,self.canvas.winfo_width());self.inspection_label.configure(wraplength=width-16);self.elo_legend.configure(wraplength=width-16)
        for label in self.legend:label.configure(wraplength=max(150,width//2-16))
        if not self.payload:
            self.canvas.configure(height=100);self.canvas.create_text(8,12,anchor='nw',width=width-20,text='Choose a matchup. Charts appear when its statistics are ready.',font=('Segoe UI',self.points));return
        record=evidence(self.payload);y=8;previous=None
        for row in record['bars']:
            group='Striking' if 'strike' in row['label'].lower() else 'Grappling' if 'Takedown' in row['label'] else 'Activity'
            if group!=previous:
                self.canvas.create_text(8,y,anchor='nw',text=group,font=('Segoe UI',self.points+1,'bold'));y+=line+10;previous=group
            def wrapped_lines(text,available):
                count=1;used=0
                for word in str(text).split():
                    length=font.measure(word+' ')
                    if used and used+length>available:count+=1;used=0
                    used+=length
                return count
            self.canvas.create_text(8,y,anchor='nw',width=width-20,text=row['label'],font=('Segoe UI',self.points,'bold'));y+=line*wrapped_lines(row['label'],width-35)+2
            maximum=1 if row['unit']=='percent' else max([v for v in (row['a'],row['b']) if v is not None]+[1])
            start=max(100,max(font.measure(side.upper()+': '+('N/A' if row[side] is None else _value(row[side],row['unit']))) for side in ('a','b'))+24);span=max(1,width-start-12)
            for side,color in (('a',COLORS['fighter_a']),('b',COLORS['fighter_b'])):
                value=row[side]
                self.canvas.create_text(8,y+line/2,anchor='w',text=side.upper()+': '+('N/A' if value is None else _value(value,row['unit'])),font=('Segoe UI',self.points))
                if value is not None:
                    self.canvas.create_rectangle(start,y+3,start+span,y+line-4,fill=COLORS['background'],outline='')
                    bar=max(0,min(span,value/maximum*span))
                    self.canvas.create_rectangle(start,y+3,start+bar,y+line-4,fill=color,outline='')
                else:self.canvas.create_text(start,y+line/2,anchor='w',text='Unavailable',fill=COLORS['muted'],font=('Segoe UI',self.points))
                y+=line
            note='Axis 0–'+_value(maximum,row['unit'])+' · '+str(row.get('direction') or 'Context dependent')
            self.canvas.create_text(8,y+2,anchor='nw',width=width-20,text=note,font=('Segoe UI',self.points),fill=COLORS['muted'])
            y+=line*wrapped_lines(note,width-30)+16
        if not record['bars']:self.canvas.create_text(8,y,anchor='nw',width=width-16,text='Paired metrics were not recorded in this report.',font=('Segoe UI',self.points));y+=line*2
        self.canvas.configure(height=y+8)
        all_values=[p['overall'] for points in record['elo'].values() for p in points if p['overall'] is not None]
        if not all_values:
            self.trend.create_text(8,20,anchor='nw',width=width-20,text='No saved Elo history. Recalculate to capture available history with the installed datasets.',font=('Segoe UI',self.points));return
        low=min(all_values)-20;high=max(all_values)+20;w=max(200,self.trend.winfo_width())
        height=max(260,line*11);self.trend.configure(height=height)
        left=max(65,font.measure(f'{high:.0f}')+20);right=w-20;top=line;bottom=height-line*3
        for fraction in (0,.5,1):
            value=low+(high-low)*fraction;cy=bottom-(bottom-top)*fraction
            self.trend.create_line(left,cy,right,cy,fill=COLORS['border'])
            self.trend.create_text(left-10,cy,anchor='e',text=f'{value:.0f}',font=('Segoe UI',self.points))
        count=max(len(points) for points in record['elo'].values())
        for i in sorted({0,(count-1)//2,count-1}):
            x=left+i*(right-left)/max(1,count-1)
            self.trend.create_text(x,bottom+line,anchor='center',text=str(i+1),font=('Segoe UI',self.points))
        self.trend.create_text((left+right)/2,height-line/2,text='Successive recorded bouts (each fighter separately)',width=max(100,right-left),font=('Segoe UI',self.points))
        for side,color in (('fighter_a',COLORS['fighter_a']),('fighter_b',COLORS['fighter_b'])):
            previous_point=None
            for i,p in enumerate(record['elo'].get(side,[])):
                if p['overall'] is None:previous_point=None;continue
                x=left+i*(right-left)/max(1,count-1);y=bottom-(p['overall']-low)/(high-low)*(bottom-top)
                if previous_point:self.trend.create_line(*previous_point,x,y,fill=color,width=2)
                self.trend.create_oval(x-3,y-3,x+3,y+3,fill=color,outline=color)
                self.point_positions.append((side,i,p,x,y));previous_point=(x,y)
        self.mark_selected()
