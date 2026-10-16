"""Result widgets render only the displayed report's frozen evidence."""
import tkinter as tk
from tkinter import ttk
from analyzer_theme import COLORS, readable_timestamp


class ScrollPanel(ttk.Frame):
    """One outer viewport with local wheel/key handling and focus visibility."""
    def __init__(self, parent):
        super().__init__(parent, style='Surface.TFrame')
        self.columnconfigure(0, weight=1); self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, background=COLORS['surface'], highlightthickness=2, highlightbackground=COLORS['surface'], highlightcolor=COLORS['primary'], takefocus=True)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(self, command=self.canvas.yview)
        scrollbar.grid(row=0, column=1, sticky='ns'); self.canvas.configure(yscrollcommand=scrollbar.set)
        self.content = ttk.Frame(self.canvas, style='Surface.TFrame', padding=16)
        self.content.columnconfigure(0, weight=1)
        self.item = self.canvas.create_window(0, 0, window=self.content, anchor='nw')
        self.canvas.bind('<Configure>', self.resize)
        self.content.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Next>', lambda e: self.page(1)); self.canvas.bind('<Prior>', lambda e: self.page(-1))
        self.canvas.bind('<Down>', lambda e: self.scroll(1)); self.canvas.bind('<Up>', lambda e: self.scroll(-1))

    def resize(self, event):
        self.canvas.itemconfigure(self.item, width=event.width)

    def scroll(self, units):
        if self.content.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(units, 'units')
        return 'break'

    def page(self, direction):
        self.canvas.yview_scroll(direction, 'pages'); return 'break'

    def bind_children(self):
        def bind(widget):
            widget.bind('<MouseWheel>', lambda e: self.scroll(-int(e.delta/120)), add='+')
            widget.bind('<FocusIn>', self.reveal, add='+')
            for child in widget.winfo_children(): bind(child)
        bind(self)

    def reveal(self, event):
        widget = event.widget
        if widget is self.canvas: return
        self.update_idletasks()
        y = widget.winfo_rooty() - self.content.winfo_rooty()
        border=int(self.canvas.cget('highlightthickness'))
        top = self.canvas.canvasy(border); height = max(1,self.canvas.winfo_height()-2*border)
        if y < top or y + widget.winfo_height() > top + height:
            target = y-4 if y < top or widget.winfo_height()>height else y + widget.winfo_height() - height+4
            self.canvas.yview_moveto(max(0, target)/max(1, self.content.winfo_height()))


class MatchupPanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, style='Surface.TFrame')
        self.columnconfigure(0, weight=1); self.columnconfigure(1, weight=1)
        self.names = {}; self.values = {}; self.cards = {}
        self.mode = tk.StringVar(value='Choose a matchup to get started')
        self.context = tk.StringVar(); self.reliability = tk.StringVar(); self.metadata = tk.StringVar()
        self.mode_label = ttk.Label(self, textvariable=self.mode, style='Section.TLabel', wraplength=700)
        self.mode_label.grid(row=0, column=0, columnspan=2, sticky='w')
        ttk.Label(self, textvariable=self.context, style='Caption.TLabel').grid(row=1, column=0, columnspan=2, sticky='w', pady=(4,12))
        for col, side in enumerate(('a','b')):
            card = ttk.Frame(self, style='Surface.TFrame'); card.grid(row=2,column=col,sticky='new',padx=(0,16) if col==0 else (16,0))
            card.columnconfigure(0,weight=1); self.cards[side]=card
            self.names[side]=tk.StringVar(value='Fighter '+side.upper()); self.values[side]=tk.StringVar(value='—')
            ttk.Label(card,textvariable=self.names[side],style=f'Fighter{side.upper()}.TLabel',wraplength=350).grid(row=0,column=0,sticky='w')
            ttk.Label(card,textvariable=self.values[side],style=f'Probability{side.upper()}.TLabel').grid(row=1,column=0,sticky='w',pady=(4,0))
        self.bar=tk.Canvas(self,height=10,background=COLORS['background'],highlightthickness=0)
        self.bar.grid(row=3,column=0,columnspan=2,sticky='ew',pady=(12,10));self.bar.bind('<Configure>',lambda e:self.draw())
        ttk.Label(self,textvariable=self.reliability,style='Caption.TLabel',wraplength=800).grid(row=4,column=0,columnspan=2,sticky='w')
        ttk.Label(self,textvariable=self.metadata,style='Caption.TLabel',wraplength=800).grid(row=5,column=0,columnspan=2,sticky='w',pady=(5,0))
        self.payload=None;self.bind('<Configure>',self.layout)

    def layout(self, event=None):
        width=max(200,self.winfo_width());stacked=width<560
        for col,side in enumerate(('a','b')):
            self.cards[side].grid_configure(row=2 if not stacked or col==0 else 3,column=0 if stacked else col,
                                           columnspan=2 if stacked else 1,padx=(0,12),pady=(0,8) if stacked else 0)
            for label in self.cards[side].winfo_children(): label.configure(wraplength=max(180,width-30 if stacked else width//2-30))
        shift=1 if stacked else 0
        self.bar.grid_configure(row=3+shift)
        for label in self.winfo_children():
            if isinstance(label,ttk.Label):
                label.configure(wraplength=max(180,width-12))
                if label.cget('textvariable')==str(self.reliability):label.grid_configure(row=4+shift)
                if label.cget('textvariable')==str(self.metadata):label.grid_configure(row=5+shift)

    def show(self,payload):
        self.payload=payload; state=payload.get('result_state','complete')
        complete=state=='complete'
        modes={'comparison':'Statistics only · no prediction calculated','pending':'Prediction running · statistics available',
               'cancelled':'Prediction cancelled · partial evidence','failed':'Prediction failed · partial evidence'}
        self.mode.set('Model prediction: '+str(payload.get('predicted_winner','Unavailable')) if complete else
                      modes[state] if state in ('cancelled','failed') else 'Initial comparison · partial evidence; advanced statistics pending' if payload.get('quick_comparison') else modes.get(state,'Partial evidence'))
        self.context.set(str(payload.get('division',''))+' · Fight date '+str(payload.get('fight_date','Not recorded')))
        for side in ('a','b'):
            self.names[side].set(payload['fighter_'+side])
            value=payload.get('fighter_'+side+'_win_probability')
            self.values[side].set(f'{value:.1%}' if complete and value is not None else '—')
        reliability=''
        if complete:
            if 'reliability_label' in payload:
                score=payload.get('reliability_score')
                reliability='Probability stability: '+str(payload['reliability_label'])+(f' ({score}/100)' if score is not None else '')+' · not outcome certainty'
            elif 'confidence_tier' in payload:reliability='Recorded confidence tier: '+str(payload['confidence_tier'])+' · not outcome certainty'
            else:reliability='Reliability not recorded; see the report for limitations.'
        self.reliability.set(reliability)
        self.metadata.set('Generated '+readable_timestamp(payload.get('generated_at'))+(' · Reused saved analysis' if payload.get('reused') else ''))
        self.bar.grid() if complete else self.bar.grid_remove()
        self.draw()

    def draw(self):
        self.bar.delete('all')
        if not self.payload or self.payload.get('result_state','complete')!='complete':return
        p=self.payload.get('fighter_a_win_probability')
        if p is None:return
        width=max(1,self.bar.winfo_width())
        self.bar.create_rectangle(0,0,width*p,10,fill=COLORS['fighter_a'],outline='')
        self.bar.create_rectangle(width*p,0,width,10,fill=COLORS['fighter_b'],outline='')


class EvidencePanel(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent,style='Surface.TFrame')
        self.columnconfigure(0,weight=1);self.columnconfigure(1,weight=1)
        self.texts={};self.labels=[]
        for col,side in enumerate(('a','b')):
            self.texts[side]=tk.StringVar(value='No analysis selected.')
            label=ttk.Label(self,textvariable=self.texts[side],style='Surface.TLabel',wraplength=350,justify='left')
            label.grid(row=0,column=col,sticky='nw',padx=(0,16));self.labels.append(label)
        self.shared=tk.StringVar();self.note=ttk.Label(self,textvariable=self.shared,style='Warning.TLabel',wraplength=800,justify='left')
        self.note.grid(row=1,column=0,columnspan=2,sticky='w',pady=(10,0))
        self.bind('<Configure>',self.layout)

    def layout(self,event=None):
        width=max(200,self.winfo_width());stacked=width<560
        for i,label in enumerate(self.labels):
            label.grid_configure(row=i if stacked else 0,column=0 if stacked else i,columnspan=2 if stacked else 1,pady=(0,8))
            label.configure(wraplength=max(180,width-20 if stacked else width//2-24))
        self.note.grid_configure(row=2 if stacked else 1);self.note.configure(wraplength=max(180,width-20))

    def show(self,payload):
        from analyzer_evidence import format_evidence
        record=payload.get('evidence_quality')
        if not record:
            for side in ('a','b'):self.texts[side].set(payload['fighter_'+side]+'\nEvidence not recorded in this saved analysis.')
            self.shared.set('Recalculate to capture evidence with the installed datasets.');return
        lines=format_evidence(payload,compact=True).splitlines()
        for side in ('a','b'):
            row=record['fighters'][side]
            count=lambda field:str(row[field]) if row.get(field) is not None else 'Not recorded'
            self.texts[side].set(str(row.get('name') or payload['fighter_'+side])+'\n'+count('eligible_bouts')+' eligible UFC bouts · '+count('division_bouts')+' in selected division\nLatest included bout: '+str(row.get('latest_bout') or 'Not recorded'))
        self.shared.set('\n'.join(lines[2:]))

    def text(self):
        return '\n'.join([self.texts['a'].get(),self.texts['b'].get(),self.shared.get()])
