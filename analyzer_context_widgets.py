"""Native views for frozen recent bouts and descriptive form."""
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from analyzer_bout_context import form_rows, bout_text, UNRECORDED, results_text

class BoutDetails(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent);self.columnconfigure(0,weight=1)
        self.button=ttk.Button(self,text='Show bout details',command=self.toggle)
        self.button.grid(row=0,column=0,sticky='w')
        self.text=ScrolledText(self,height=12,wrap='word',font=('Segoe UI',10))
        self.text.grid(row=1,column=0,sticky='ew',pady=4);self.text.grid_remove()
        self.expanded=False;self.value=None;self.missing_message=UNRECORDED
    def show(self,bout):
        self.value=bout;self.text.configure(state='normal');self.text.delete('1.0','end')
        self.text.insert('1.0',bout_text(bout) if bout else self.missing_message);self.text.configure(state='disabled')
    def toggle(self,event=None):
        self.expanded=not self.expanded
        self.text.grid() if self.expanded else self.text.grid_remove()
        self.button.configure(text='Hide bout details' if self.expanded else 'Show bout details')
        return 'break'
    def reset(self,missing_message=UNRECORDED):
        if self.expanded:self.toggle()
        self.missing_message=missing_message
        self.show(None)

class RecentForm(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent);self.columnconfigure(0,weight=1);self.payload={}
        self.toggle_button=ttk.Button(self,text='Recent form versus UFC career ▸',command=self.toggle)
        self.toggle_button.grid(row=0,column=0,sticky='w',pady=4)
        self.body=ttk.Frame(self);self.body.columnconfigure(0,weight=1)
        self.window=tk.StringVar(value='5');controls=ttk.Frame(self.body);controls.grid(row=0,column=0,sticky='w')
        for value in ('3','5'):ttk.Radiobutton(controls,text='Last '+value,variable=self.window,value=value,command=self.render).pack(side='left',padx=5)
        self.caption=tk.StringVar(value=UNRECORDED)
        ttk.Label(self.body,textvariable=self.caption,wraplength=780).grid(row=1,column=0,sticky='w',pady=5)
        self.tree=ttk.Treeview(self.body,columns=('fighter','metric','recent','career','delta'),show='headings',height=8)
        for name,label,width in [('fighter','Fighter',150),('metric','Metric',250),('recent','Recent',95),('career','Career',95),('delta','Difference',95)]:
            self.tree.heading(name,text=label);self.tree.column(name,width=width,minwidth=80)
        self.tree.grid(row=2,column=0,sticky='ew')
        y=ttk.Scrollbar(self.body,command=self.tree.yview);y.grid(row=2,column=1,sticky='ns');self.tree.configure(yscrollcommand=y.set)
        x=ttk.Scrollbar(self.body,orient='horizontal',command=self.tree.xview);x.grid(row=3,column=0,sticky='ew');self.tree.configure(xscrollcommand=x.set)
        self.support=tk.StringVar(value='Select a metric for its recent / career support.')
        ttk.Label(self.body,textvariable=self.support,wraplength=780).grid(row=4,column=0,sticky='w',pady=5)
        self.tree.bind('<<TreeviewSelect>>',self.selected);self.expanded=False;self.supports={}
    def show(self,payload):self.payload=payload;self.render()
    def toggle(self,event=None):
        self.expanded=not self.expanded
        self.body.grid(row=1,column=0,sticky='ew') if self.expanded else self.body.grid_remove()
        self.toggle_button.configure(text='Recent form versus UFC career '+('▾' if self.expanded else '▸'))
    def render(self):
        self.tree.delete(*self.tree.get_children());self.supports={};self.support.set('Select a metric for its recent / career support.')
        if not self.payload.get('recent_form'):
            state=self.payload.get('result_state','complete')
            message='Recent form will be captured when this analysis finishes.' if state=='pending' or self.payload.get('quick_comparison') else 'Recent form was not captured before this operation stopped. Run a new analysis to include it.' if state in ('failed','cancelled') else UNRECORDED
            self.caption.set(message);return
        form=self.payload['recent_form'];parts=[]
        for side in ('fighter_a','fighter_b'):
            windows=form[side]['windows'];data=windows[self.window.get()];career=windows['career']
            parts.append(self.payload[side]+f": {data['bout_count']} recent / {career['bout_count']} career bouts; "+results_text(data['results'])+(' · recent and career cover the same bouts' if data['bout_count']==career['bout_count'] else ''))
            for row in form_rows(self.payload,side,self.window.get()):
                item=self.tree.insert('','end',values=(self.payload[side],*row[:4]));self.supports[item]=row[4]
        self.caption.set('\n'.join(parts)+f"\nAll UFC divisions; before {form['history_cutoff']}. Career includes recent bouts. Observed pooled totals; no model priors. Same-day ties use fight ID. Select a metric for support; opponent context is in Recent fights.")
    def selected(self,event=None):
        selected=self.tree.selection()
        if selected:self.support.set(self.supports.get(selected[0],''))
