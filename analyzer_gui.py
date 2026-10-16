"""UFC Matchup Analyzer's minimal, portable Tk interface."""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parent))

# The official embedded runtime deliberately omits Tcl/Tk; our package supplies it.
runtime=Path(sys.executable).resolve().parent
_dll_directory=os.add_dll_directory(str(runtime/'DLLs')) if os.name=='nt' and (runtime/'DLLs').exists() else None
if (runtime/'tcl/tcl8.6').exists():
    os.environ['TCL_LIBRARY']=str(runtime/'tcl/tcl8.6')
    os.environ['TK_LIBRARY']=str(runtime/'tcl/tk8.6')
elif list((runtime/'tcl').glob('libtcl9*.zip')):
    os.environ.pop('TCL_LIBRARY',None)
    os.environ.pop('TK_LIBRARY',None)

import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from tkinter.scrolledtext import ScrolledText
from analyzer_support import ROOT,VERSION,atomic_json
from analyzer_catalog import FighterCatalog,IdentityError,MEN_DIVISIONS,WOMEN_DIVISIONS,iso_date,key,validate_matchup
from analyzer_controller import WorkerController
from analyzer_results import format_result,result_filename
from analyzer_reporting import report_sections,overview_rows,format_html
from analyzer_history import History,fingerprint
from analyzer_widgets import CalendarDialog,SuggestPopup
from analyzer_theme import COLORS, SIZES, apply_theme, readable_timestamp
from analyzer_presentation import ScrollPanel, MatchupPanel, EvidencePanel
from analyzer_errors import STATES, diagnostic_text
from analyzer_fight_history import display_row, OLD_HISTORY_MESSAGE

DIVISIONS={**{'Men — '+x:('men',x) for x in MEN_DIVISIONS},**{'Women — '+x:('women',x) for x in WOMEN_DIVISIONS}}

def enable_dpi_awareness():
    if os.name=='nt':
        import ctypes
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError,OSError):
            try:ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except (AttributeError,OSError):pass

class AnalyzerApp:
    def __init__(self,window,root=ROOT,controller=None,autostart=True):
        self.window=window;self.root=Path(root);self.controller=controller or WorkerController(root)
        self.catalogs={};self.selection={};self.result=None;self.result_text='';self.ready=False;self.last_log=None;self.closing=False;self.last_request=None;self.pending_terminal=None
        self.preferences_path=self.root/'.runtime/ui_preferences.json'
        try:self.preferences=json.loads(self.preferences_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):self.preferences={}
        self.window.title('UFC Matchup Analyzer')
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        style=ttk.Style(window)
        if 'vista' in style.theme_names():style.theme_use('vista')
        style.configure('Title.TLabel',font=('Segoe UI',17,'bold'))
        style.configure('Hint.TLabel',foreground='#56616e')
        scale=float(window.tk.call('tk','scaling'))/(96/72)
        width=min(round(900*scale),window.winfo_screenwidth()-60)
        height=min(round(660*scale),window.winfo_screenheight()-80)
        window.geometry(f'{width}x{height}')
        window.minsize(min(round(720*scale),width),min(round(520*scale),height))
        window.columnconfigure(0,weight=1);window.rowconfigure(0,weight=1)
        frame=ttk.Frame(window,padding=18);frame.grid(sticky='nsew');frame.columnconfigure(1,weight=1);frame.rowconfigure(8,weight=1)
        ttk.Label(frame,text='UFC Matchup Analyzer',style='Title.TLabel').grid(row=0,column=0,columnspan=2,sticky='w')
        ttk.Label(frame,text='Choose a matchup. Analyze it locally. Copy or save the results.',style='Hint.TLabel').grid(row=1,column=0,columnspan=2,sticky='w',pady=(2,15))
        self.division=tk.StringVar(value=self.preferences.get('division','Men — Lightweight'))
        if self.division.get() not in DIVISIONS:self.division.set('Men — Lightweight')
        self.date=tk.StringVar(value=dt.date.today().isoformat())
        self.names={label:tk.StringVar(value=self.preferences.get('fighter_'+label,'')) for label in ('a','b')}
        ttk.Label(frame,text='Division').grid(row=2,column=0,sticky='w',padx=(0,15),pady=5)
        self.division_box=ttk.Combobox(frame,textvariable=self.division,values=list(DIVISIONS),state='readonly');self.division_box.grid(row=2,column=1,sticky='ew',pady=5)
        self.division_box.bind('<<ComboboxSelected>>',self.change_division)
        ttk.Label(frame,text='Fight date (YYYY-MM-DD)').grid(row=3,column=0,sticky='w',padx=(0,15),pady=5)
        self.date_entry=ttk.Entry(frame,textvariable=self.date);self.date_entry.grid(row=3,column=1,sticky='ew',pady=5)
        self.name_boxes={}
        for row,label in ((4,'a'),(5,'b')):
            ttk.Label(frame,text='Fighter '+label.upper()).grid(row=row,column=0,sticky='w',pady=5)
            box=ttk.Combobox(frame,textvariable=self.names[label]);box.grid(row=row,column=1,sticky='ew',pady=5);self.name_boxes[label]=box
            box.bind('<KeyRelease>',lambda event,label=label:self.search(label))
            box.bind('<<ComboboxSelected>>',lambda event,label=label:self.selection.pop(label,None))
        ttk.Label(frame,text='Type part of a name, then use ▼ to see matching fighters.',style='Hint.TLabel').grid(row=6,column=1,sticky='w',pady=(0,10))
        actions=ttk.Frame(frame);actions.grid(row=7,column=0,columnspan=2,sticky='ew',pady=(0,12))
        self.analyze_button=ttk.Button(actions,text='Analyze',command=self.analyze);self.analyze_button.pack(side='left')
        self.cancel_button=ttk.Button(actions,text='Cancel',command=self.cancel,state='disabled');self.cancel_button.pack(side='left',padx=8)
        self.update_button=ttk.Button(actions,text='Update datasets',command=lambda:self.start_operation('update'));self.update_button.pack(side='right')
        report_frame=ttk.Frame(frame);report_frame.grid(row=8,column=0,columnspan=2,sticky='nsew')
        report_frame.columnconfigure(0,weight=1);report_frame.rowconfigure(0,weight=1)
        self.output=ScrolledText(report_frame,wrap='none',height=14,font=('Consolas',10),background='white',foreground='#182230',padx=12,pady=10)
        self.output.grid(row=0,column=0,sticky='nsew')
        self.report_horizontal=ttk.Scrollbar(report_frame,orient='horizontal',command=self.output.xview)
        self.report_horizontal.grid(row=1,column=0,sticky='ew');self.output.configure(xscrollcommand=self.report_horizontal.set)
        self.set_text('Enter two fighters and click Analyze.\n\nThe selected model trains on your computer. An analysis usually takes a few minutes.\nInternet access is only needed for dataset updates.\n')
        self.output.bind('<Control-a>',self.select_all)
        footer=ttk.Frame(frame);footer.grid(row=9,column=0,columnspan=2,sticky='ew',pady=(10,8))
        self.copy_button=ttk.Button(footer,text='Copy results',command=self.copy,state='disabled');self.copy_button.pack(side='left')
        self.save_button=ttk.Button(footer,text='Save results…',command=self.save,state='disabled');self.save_button.pack(side='left',padx=8)
        help_button=ttk.Menubutton(footer,text='Help');help_button.pack(side='right')
        self.help_menu=tk.Menu(help_button,tearoff=False)
        for label,command in [('Quick instructions',self.help),('Check installation',lambda:self.start_operation('doctor')),('Open diagnostics',self.open_diagnostics),('Rebuild local features',lambda:self.start_operation('rebuild')),('Restore previous datasets',self.restore)]:self.help_menu.add_command(label=label,command=command)
        help_button['menu']=self.help_menu
        self.progress=ttk.Progressbar(frame,mode='indeterminate');self.progress.grid(row=10,column=0,columnspan=2,sticky='ew',pady=(0,7))
        self.status=tk.StringVar(value='Checking installation…');ttk.Label(frame,textvariable=self.status,wraplength=width-45).grid(row=11,column=0,columnspan=2,sticky='w')
        self.freshness=tk.StringVar(value='Datasets: checking…');ttk.Label(frame,textvariable=self.freshness,style='Hint.TLabel').grid(row=12,column=0,columnspan=2,sticky='w',pady=(4,0))
        self.stage_message='';self.controls()
        window.bind('<Control-Return>',lambda event:self.analyze())
        window.bind('<Control-Shift-C>',lambda event:self.copy())
        self.poll_id=window.after(150,self.poll)
        if autostart:window.after(10,lambda:self.start_operation('startup'))

    def set_text(self,text):
        self.output.configure(state='normal');self.output.delete('1.0','end');self.output.insert('1.0',text);self.output.configure(state='disabled');self.output.xview_moveto(0);self.output.yview_moveto(0)

    def select_all(self,event=None):
        self.output.tag_add('sel','1.0','end-1c');return 'break'

    def set_help_entry_state(self,index,state):
        # Windows redraws a posted native menu even for unchanged settings.
        # Polling must only configure entries when their availability changes.
        if self.help_menu.entrycget(index,'state')!=state:
            self.help_menu.entryconfigure(index,state=state)

    def controls(self):
        busy=self.controller.busy
        state='normal' if self.ready and not busy else 'disabled'
        self.analyze_button.configure(state=state);self.update_button.configure(state=state)
        self.division_box.configure(state='readonly' if not busy else 'disabled')
        self.date_entry.configure(state='normal' if not busy else 'disabled')
        for box in self.name_boxes.values():box.configure(state='normal' if not busy else 'disabled')
        self.cancel_button.configure(state='normal' if busy and self.controller.cancellable else 'disabled')
        for index in (1,3,4):self.set_help_entry_state(index,'disabled' if busy else 'normal')
        if busy:self.progress.configure(mode='indeterminate');self.progress.start(15)
        else:self.progress.stop();self.progress.configure(mode='determinate',value=0)

    def change_division(self,event=None):
        self.selection.clear()
        for label in ('a','b'):self.search(label)

    def search(self,label):
        sex,_=DIVISIONS[self.division.get()]
        catalog=self.catalogs.get(sex)
        if label in self.selection and self.selection[label][0]!=self.names[label].get():self.selection.pop(label,None)
        self.name_boxes[label]['values']=catalog.search(self.names[label].get()) if catalog else ()

    def choose_identity(self,label,error,catalog):
        if not error.candidates:
            messagebox.showerror('Check fighter '+label.upper(),str(error),parent=self.window);return None
        dialog=tk.Toplevel(self.window);dialog.title('Choose fighter '+label.upper());dialog.transient(self.window);dialog.grab_set()
        dialog.columnconfigure(0,weight=1);dialog.rowconfigure(1,weight=1)
        ttk.Label(dialog,text='Select the correct identity:' if error.ambiguous else 'Fighter not found. Did you mean:',padding=12).grid(sticky='w')
        choices=tk.Listbox(dialog,height=min(8,len(error.candidates)),width=90,exportselection=False);choices.grid(row=1,column=0,sticky='nsew',padx=12)
        for identity in error.candidates:
            description=catalog.suggestion_description(identity,self.date.get().strip(),DIVISIONS[self.division.get()][1]) if getattr(self,'enhanced',False) else catalog.describe(identity)
            choices.insert('end',description)
        chosen=[]
        def accept(event=None):
            selection=choices.curselection()
            if selection:chosen.append(error.candidates[selection[0]]);dialog.destroy()
        buttons=ttk.Frame(dialog,padding=12);buttons.grid(row=2,column=0,sticky='e')
        ttk.Button(buttons,text='Use selected fighter',command=accept).pack(side='left')
        ttk.Button(buttons,text='Cancel',command=dialog.destroy).pack(side='left',padx=(8,0))
        choices.bind('<Double-1>',accept);choices.bind('<Return>',accept);dialog.bind('<Escape>',lambda event:dialog.destroy());choices.focus_set()
        self.window.wait_window(dialog)
        return chosen[0] if chosen else None

    def prediction_request(self,workers=None):
        if not self.ready:raise ValueError('Wait for the installation check to finish.')
        sex,division=DIVISIONS[self.division.get()];date=iso_date(self.date.get().strip());catalog=self.catalogs[sex]
        identities={}
        for label in ('a','b'):
            selected=self.selection.get(label)
            identifier=selected[1] if selected and key(selected[0])==key(self.names[label].get()) else None
            if identifier is None:self.selection.pop(label,None)
            try:identity=catalog.resolve(self.names[label].get().strip(),identifier)
            except IdentityError as exc:
                identity=self.choose_identity(label,exc,catalog)
                if not identity:return None
                # A fuzzy suggestion can itself be ambiguous; resolving again enforces safety.
                identity=catalog.resolve(identity[0],identity[1] if sex=='men' else None)
            identities[label]=identity;self.selection[label]=identity;self.names[label].set(identity[0])
        validate_matchup(sex,division,date,identities['a'],identities['b'])
        request=dict(operation='predict',sex=sex,division=division,fight_date=date,fighter_a=identities['a'][0],fighter_b=identities['b'][0],fighter_a_id=identities['a'][1],fighter_b_id=identities['b'][1])
        if workers:request['workers']=workers
        return request

    def analyze(self):
        if self.controller.busy:return
        try:
            request=self.prediction_request()
            if request:self.start(request)
        except (ValueError,OSError,argparse.ArgumentTypeError) as exc:messagebox.showerror('Check your matchup',str(exc),parent=self.window)

    def start(self,request):
        if self.controller.busy:return
        try:
            self.controller.start(request);self.last_request=dict(request);self.stage_message='Starting…';self.controls();self.status.set('Starting…')
        except (OSError,RuntimeError) as exc:messagebox.showerror('Could not start',str(exc)+'\n\nExtract the complete ZIP into a writable folder.',parent=self.window)

    def start_operation(self,operation):
        if self.controller.busy:return
        if operation=='rebuild' and not messagebox.askyesno('Rebuild local features','Rebuild both models’ feature datasets from your local inputs? This can take several minutes.',parent=self.window):return
        self.start(dict(operation=operation))

    def cancel(self):
        if self.controller.cancel():self.stage_message='Cancelling safely…';self.cancel_button.configure(state='disabled')

    def poll(self):
        if getattr(self,'poll_id',None):
            try:self.window.after_cancel(self.poll_id)
            except tk.TclError:pass
        try:
            for event in self.controller.poll():
                if event['type']=='progress':self.stage_message='Cancelling safely…' if getattr(self.controller,'cancel_requested',False) else event['message']
                else:self.pending_terminal=event
            if self.controller.busy:
                elapsed=int(time.monotonic()-self.controller.started)
                self.status.set(f'{self.stage_message}  ·  {elapsed//60}:{elapsed%60:02d} elapsed')
            elif self.pending_terminal:
                event=self.pending_terminal;self.pending_terminal=None;self.handle_terminal(event)
            self.controls()
            if self.closing and not self.controller.busy:self.destroy();return
        except (OSError,ValueError,RuntimeError) as exc:
            self.controller.terminate();self.status.set('Operation stopped. Use Data & maintenance → Check installation.')
            messagebox.showerror('Operation stopped',str(exc),parent=self.window);self.controls()
        self.poll_id=self.window.after(150,self.poll)

    def handle_terminal(self,event):
        if event['type']=='error':
            self.last_log=event.get('log');self.status.set(event['message'])
            if event['code']=='cancelled':return
            if self.closing:return
            if event['code']=='worker_permission' and not self.closing and messagebox.askyesno('Retry with one worker','Windows blocked a parallel worker. Retry this analysis using one worker?',parent=self.window):
                self.start(dict(self.last_request,workers=1));return
            messagebox.showerror('Operation could not finish',event['message']+'\n\nUse Data & maintenance → Open diagnostics for details.',parent=self.window)
            return
        operation=event['operation'];payload=event['payload']
        if operation=='predict':
            self.result=payload;self.result_text=format_result(payload);self.set_text(self.result_text)
            self.copy_button.configure(state='normal');self.save_button.configure(state='normal');self.status.set('Analysis complete. Copy or save the results.')
            return
        self.ready=payload['ready']
        self.freshness.set('Datasets through: men '+payload['dates']['men']+'  ·  women '+payload['dates']['women'])
        if self.ready:
            self.catalogs={sex:FighterCatalog.from_payload(payload['catalogs'][sex]) if payload.get('catalogs') else FighterCatalog(sex,self.root) for sex in ('men','women')};self.change_division()
            self.status.set('Ready to analyze.' if operation in ('startup','doctor') else 'Datasets restored.' if operation=='recover' else 'Already up to date.' if payload.get('status')=='no_changes' else 'Datasets updated and validated.' if operation=='update' else 'Local features rebuilt and validated.')
            if operation in ('update','rebuild') and not self.closing:
                summary='Already up to date.' if payload.get('status')=='no_changes' else '\n'.join(sex.title()+': '+str(payload['summary'].get(sex,{}).get('added_fights',0))+' new completed fights' for sex in ('men','women'))
                messagebox.showinfo('Dataset update complete',summary+'\n\n'+self.freshness.get(),parent=self.window)
            elif payload.get('recovered'):messagebox.showinfo('Interrupted update recovered','The previous valid datasets were restored. You can analyze again.',parent=self.window)
            elif operation=='doctor':messagebox.showinfo('Installation check','All required installation and dataset checks passed.\n\n'+self.freshness.get(),parent=self.window)
        else:
            failures=[c.get('path',c.get('package',c.get('component',''))) + ': '+c.get('message','Required component is missing or has the wrong version.') for c in payload['checks'] if c['status']=='FAIL']
            self.status.set('Installation needs attention. Analysis is disabled.')
            if not self.result:self.set_text('INSTALLATION CHECK\n\n'+'\n'.join(failures)+'\n\nFor missing or damaged bundled files, extract a fresh copy of the complete ZIP. For an interrupted update, use Data & maintenance → Check installation.\n')
            request_path=getattr(self.controller,'request_path',None)
            if request_path:self.last_log=self.root/'.runtime/logs'/(request_path.stem+'.log')
            messagebox.showerror('Installation needs attention','\n'.join(failures[:3])+'\n\nUse Data & maintenance → Open diagnostics for all check details. Extract a fresh complete ZIP for missing or damaged bundled files.',parent=self.window)

    def copy(self):
        if self.result_text:self.window.clipboard_clear();self.window.clipboard_append(self.result_text);self.status.set('Results copied to the clipboard.')

    def save(self):
        if not self.result:return
        path=filedialog.asksaveasfilename(parent=self.window,title='Save matchup analysis',initialfile=result_filename(self.result),initialdir=self.preferences.get('save_directory',str(Path.home()/'Documents')),defaultextension='.txt',filetypes=[('Text files','*.txt')],confirmoverwrite=True)
        if not path:return
        try:
            Path(path).write_text(self.result_text,encoding='utf-8',newline='\n');self.preferences['save_directory']=str(Path(path).parent);self.status.set('Results saved to '+str(path))
        except OSError as exc:messagebox.showerror('Could not save',str(exc)+'\nChoose a writable folder.',parent=self.window)

    def restore(self):
        if self.controller.busy:return
        if messagebox.askyesno('Restore previous datasets','Undo your latest successful dataset update or rebuild and restore its backup?',parent=self.window):self.start_operation('recover')

    def open_diagnostics(self):
        path=Path(self.last_log) if self.last_log else self.root/'.runtime/logs'
        if not path.exists():path=self.root/'.runtime'
        try:
            if os.name=='nt':os.startfile(path)
            else:messagebox.showinfo('Diagnostics',str(path),parent=self.window)
        except OSError as exc:messagebox.showerror('Diagnostics',str(exc),parent=self.window)

    def help(self):
        messagebox.showinfo('Quick instructions','1. Choose a men’s or women’s division.\n2. Enter the fight date as YYYY-MM-DD.\n3. Enter two fighters. Use ▼ for matching names.\n4. Click Analyze and allow a few minutes.\n5. Copy results or save them as a text file.\n\nPredictions work offline. Update datasets needs internet and updates both models safely. Updates rebuild features; predictions train the selected algorithm locally.\n\nHistorical matchups exclude information from the selected fight date and later. Probabilities are estimates, not guarantees.\n\nKeyboard: Ctrl+Enter analyzes; Ctrl+Shift+C copies results.',parent=self.window)

    def close(self):
        if self.controller.busy:
            if not self.controller.cancellable:
                messagebox.showinfo('Please wait','The app is checking or committing data. Wait for this step to finish before closing.',parent=self.window);return
            if not messagebox.askyesno('Close the app','Cancel the current operation safely, then close?',parent=self.window):return
            self.closing=True;self.cancel();return
        self.destroy()

    def destroy(self):
        try:
            self.preferences.update(division=self.division.get(),fighter_a=self.names['a'].get(),fighter_b=self.names['b'].get())
            atomic_json(self.preferences_path,self.preferences)
        except OSError:pass
        if self.poll_id:
            try:self.window.after_cancel(self.poll_id)
            except tk.TclError:pass
        self.window.destroy()

LegacyAnalyzerApp=AnalyzerApp

class AnalyzerApp(LegacyAnalyzerApp):
    def __init__(self,window,root=ROOT,controller=None,autostart=True):
        self.enhanced=False
        super().__init__(window,root,controller,False)
        for child in window.winfo_children():
            if isinstance(child,ttk.Frame):child.destroy()
        apply_theme(window)
        self.enhanced=True;self.history=History(self.root);self.history_contexts={};self.backup_available=False
        self.history_ready=not autostart;self.active_refresh=None;self.pending_comparison=None
        self.viewing_other=False;self.new_result=None;self.preview=None;self.rows={};self.search_tasks={};self.coverage_task=None;self.progress_running=False
        self.active_sex=DIVISIONS[self.division.get()][0];self.category_names=self.preferences.get('category_names',{})
        self.collapsed=bool(self.preferences.get('inputs_collapsed',False));self.font_size=tk.StringVar(value=self.preferences.get('text_size','Medium'))
        self.history_setting=tk.BooleanVar(value=self.preferences.get('history_enabled',True));self.pending_stage=None
        self.frame=ttk.Frame(window,padding=14);self.frame.grid(row=0,column=0,sticky='nsew');self.frame.columnconfigure(0,weight=1);self.frame.rowconfigure(4,weight=1)
        title=ttk.Frame(self.frame);title.grid(row=0,column=0,sticky='ew');title.columnconfigure(0,weight=1)
        self.title_label=ttk.Label(title,text='UFC Matchup Analyzer',style='Title.TLabel',wraplength=430);self.title_label.grid(row=0,column=0,sticky='w')
        self.history_button=ttk.Button(title,text='Recent analyses',command=self.show_history);self.history_button.grid(row=0,column=1,padx=8)
        view_button=ttk.Menubutton(title,text='View');view_button.grid(row=0,column=2)
        self.view_menu=tk.Menu(view_button,tearoff=False);view_button['menu']=self.view_menu
        for label in ('Small','Medium','Large'):
            self.view_menu.add_radiobutton(label=label+' text',variable=self.font_size,value=label,command=self.change_font)
        self.view_menu.add_separator();self.view_menu.add_checkbutton(label='Keep recent analyses and reuse valid results',variable=self.history_setting,command=self.save_history_setting)
        self.input_toggle=ttk.Button(title,text='Edit matchup' if self.collapsed else 'Hide inputs',command=self.toggle_inputs);self.input_toggle.grid(row=0,column=3,padx=(8,0))
        self.matchup_header=tk.StringVar(value='Choose a division, date and two fighters.')
        ttk.Label(self.frame,textvariable=self.matchup_header,style='Hint.TLabel',wraplength=850).grid(row=1,column=0,sticky='w',pady=(4,8))
        self.input_scroll=ScrollPanel(self.frame);self.input_scroll.grid(row=2,column=0,sticky='ew')
        self.input_scroll.canvas.configure(height=180,background=COLORS['background'])
        self.inputs=self.input_scroll.content;self.inputs.configure(style='TFrame',padding=8)
        self.inputs.columnconfigure(0,weight=1);self.inputs.columnconfigure(2,weight=1)
        division_frame=ttk.Frame(self.inputs);division_frame.grid(row=0,column=0,sticky='ew');division_frame.columnconfigure(0,weight=1)
        ttk.Label(division_frame,text='Division').grid(row=0,column=0,sticky='w')
        self.division_box=ttk.Combobox(division_frame,textvariable=self.division,values=list(DIVISIONS),state='readonly');self.division_box.grid(row=1,column=0,sticky='ew');self.division_box.bind('<<ComboboxSelected>>',self.change_division)
        date_frame=ttk.Frame(self.inputs);date_frame.grid(row=0,column=2,sticky='ew');date_frame.columnconfigure(0,weight=1)
        ttk.Label(date_frame,text='Fight date (YYYY-MM-DD)').grid(row=0,column=0,columnspan=3,sticky='w')
        self.date_entry=ttk.Entry(date_frame,textvariable=self.date);self.date_entry.grid(row=1,column=0,sticky='ew')
        self.today_button=ttk.Button(date_frame,text='Today',command=lambda:self.date.set(dt.date.today().isoformat()));self.today_button.grid(row=1,column=1,padx=5)
        self.calendar_button=ttk.Button(date_frame,text='Calendar…',command=lambda:CalendarDialog(window,self.date.get(),self.date.set));self.calendar_button.grid(row=1,column=2)
        self.errors={label:tk.StringVar() for label in ('date','a','b')}
        ttk.Label(date_frame,textvariable=self.errors['date'],foreground='#a12622').grid(row=2,column=0,columnspan=3,sticky='w')
        self.name_boxes={};self.popups={};self.coverage_labels={}
        for column,label in ((0,'a'),(2,'b')):
            group=ttk.Frame(self.inputs);group.grid(row=1,column=column,sticky='ew',pady=(5,0));group.columnconfigure(0,weight=1)
            ttk.Label(group,text='Fighter '+label.upper()).grid(row=0,column=0,sticky='w')
            box=ttk.Combobox(group,textvariable=self.names[label]);box.grid(row=1,column=0,sticky='ew');self.name_boxes[label]=box
            popup=SuggestPopup(box,lambda identity,label=label:self.select_suggestion(label,identity));self.popups[label]=popup
            box.bind('<KeyRelease>',lambda event,label=label:self.search(label,event));box.bind('<<ComboboxSelected>>',lambda e:self.queue_coverage())
            ttk.Label(group,textvariable=self.errors[label],foreground='#a12622',wraplength=430).grid(row=2,column=0,sticky='w')
            self.coverage_labels[label]=tk.StringVar(value='Select a fighter to see dated history.')
            ttk.Label(group,textvariable=self.coverage_labels[label],style='Hint.TLabel',wraplength=430).grid(row=3,column=0,sticky='w')
        self.swap_button=ttk.Button(self.inputs,text='⇄ Swap',command=self.swap);self.swap_button.grid(row=1,column=1,padx=8)
        self.coverage_warning=tk.StringVar();self.date_mode=tk.StringVar()
        ttk.Label(self.inputs,textvariable=self.date_mode,style='Hint.TLabel').grid(row=2,column=0,columnspan=3,sticky='w')
        ttk.Label(self.inputs,textvariable=self.coverage_warning,foreground='#725200',wraplength=950).grid(row=3,column=0,columnspan=3,sticky='w',pady=(3,5))
        self.input_scroll.bind_children()
        self.actions=ttk.Frame(self.frame);self.actions.grid(row=3,column=0,sticky='ew',pady=(5,12))
        self.analyze_button=ttk.Button(self.actions,text='Analyze',style='Primary.TButton',command=self.analyze);self.analyze_button.pack(side='left')
        self.compare_button=ttk.Button(self.actions,text='Compare statistics only',command=self.compare);self.compare_button.pack(side='left',padx=8)
        self.cancel_button=ttk.Button(self.actions,text='Cancel',command=self.cancel)
        self.operation_hint=tk.StringVar()
        ttk.Label(self.actions,textvariable=self.operation_hint,style='Hint.TLabel').pack(side='left',padx=8)
        self.notebook=ttk.Notebook(self.frame);self.notebook.grid(row=4,column=0,sticky='nsew')
        self.overview=ttk.Frame(self.notebook);self.comparison=ttk.Frame(self.notebook,padding=12);self.report_tab=ttk.Frame(self.notebook)
        full=self.report_tab
        self.visual_tab=ttk.Frame(self.notebook,padding=12);self.recent_tab=ttk.Frame(self.notebook,padding=12)
        self.tabs={'overview':self.overview,'statistics':self.comparison,'charts':self.visual_tab,'recent':self.recent_tab,'report':full}
        for name,label in (('overview','Overview'),('statistics','Statistics'),('charts','Charts'),('recent','Recent fights'),('report','Report')):
            self.notebook.add(self.tabs[name],text=label)
        self.build_recent_tab()
        from analyzer_visuals import VisualPanel
        self.visual_panel=VisualPanel(self.visual_tab)
        self.overview.columnconfigure(0,weight=1);self.overview.rowconfigure(0,weight=1)
        self.overview_scroll=ScrollPanel(self.overview);self.overview_scroll.grid(row=0,column=0,sticky='nsew')
        content=self.overview_scroll.content
        self.summary=tk.StringVar(value='Enter a matchup and choose Analyze or Compare statistics only.')
        self.matchup_panel=MatchupPanel(content);self.matchup_panel.grid(row=0,column=0,sticky='ew')
        self.probability=self.matchup_panel.bar
        self.result_warning=tk.StringVar()
        ttk.Label(content,textvariable=self.result_warning,style='Warning.TLabel',wraplength=800).grid(row=1,column=0,sticky='ew',pady=(12,16))
        ttk.Separator(content).grid(row=2,column=0,sticky='ew',pady=(0,16))
        ttk.Label(content,text='Evidence quality',style='Section.TLabel').grid(row=3,column=0,sticky='w',pady=(0,8))
        self.evidence_panel=EvidencePanel(content);self.evidence_panel.grid(row=4,column=0,sticky='ew')
        ttk.Button(content,text='Evidence details',command=self.evidence_dialog).grid(row=5,column=0,sticky='w',pady=(8,16))
        self.matchup_observations=tk.StringVar()
        self.observation_label=ttk.Label(content,textvariable=self.matchup_observations,style='Surface.TLabel',wraplength=800)
        self.observation_label.grid(row=6,column=0,sticky='ew',pady=(0,8))
        self.summary_metrics_button=ttk.Button(content,text='View supporting metrics',command=self.summary_metrics)
        self.summary_metrics_button.grid(row=7,column=0,sticky='w',pady=(0,16))
        ttk.Button(content,text='Recent form versus UFC career',command=self.open_recent_form).grid(row=10,column=0,sticky='w',pady=8)
        ttk.Label(content,text='Key statistics',style='Section.TLabel').grid(row=8,column=0,sticky='w',pady=(0,8))
        self.overview_tree=self.table(content,9,overview=True)
        self.overview_scroll.bind_children()
        self.comparison.columnconfigure(0,weight=1);self.comparison.rowconfigure(0,weight=1)
        self.comparison_scroll=ScrollPanel(self.comparison);self.comparison_scroll.grid(row=0,column=0,sticky='nsew')
        statistics=self.comparison_scroll.content
        self.stat_legend=ttk.Frame(statistics);self.stat_legend.grid(row=0,column=0,sticky='ew',pady=(0,8))
        self.stat_names={}
        for col,side in enumerate(('a','b')):
            self.stat_legend.columnconfigure(col,weight=1)
            self.stat_names[side]=tk.StringVar(value='Fighter '+side.upper())
            ttk.Label(self.stat_legend,textvariable=self.stat_names[side],foreground=COLORS['fighter_'+side],wraplength=360).grid(row=0,column=col,sticky='nw',padx=(0,12))
        navigation=ttk.Frame(statistics);navigation.grid(row=1,column=0,sticky='ew',pady=(0,8));navigation.columnconfigure(3,weight=1)
        ttk.Label(navigation,text='Section').grid(row=0,column=0)
        self.section=tk.StringVar(value='All sections');self.section_box=ttk.Combobox(navigation,textvariable=self.section,values=['All sections'],state='readonly',width=32);self.section_box.grid(row=0,column=1,padx=8);self.section_box.bind('<<ComboboxSelected>>',lambda e:self.render_comparison())
        ttk.Label(navigation,text='Find metric').grid(row=0,column=2)
        self.filter=tk.StringVar();self.filter_entry=ttk.Entry(navigation,textvariable=self.filter);self.filter_entry.grid(row=0,column=3,sticky='ew',padx=8);self.filter.trace_add('write',lambda *a:self.render_comparison())
        ttk.Button(navigation,text='Clear',command=lambda:self.filter.set('')).grid(row=0,column=4)
        self.comparison_tree=self.table(statistics,2)
        self.details=ScrolledText(statistics,height=4,font=('Segoe UI',SIZES.get(self.font_size.get(),10)),wrap='word',background='#f7f8fa');self.details.grid(row=3,column=0,sticky='ew',pady=(8,0));self.details.insert('1.0','Select a metric to read its definition, units, and support notes.');self.details.configure(state='disabled')
        from analyzer_context_widgets import RecentForm
        self.recent_form_panel=RecentForm(statistics);self.recent_form_panel.grid(row=4,column=0,sticky='ew',pady=8)
        self.comparison_scroll.bind_children()
        self.comparison_tree.bind('<MouseWheel>',lambda e:self.comparison_tree.yview_scroll(-int(e.delta/120),'units') or 'break')
        self.details.bind('<MouseWheel>',lambda e:self.details.yview_scroll(-int(e.delta/120),'units') or 'break')
        full.columnconfigure(0,weight=1);full.rowconfigure(0,weight=1)
        self.output=ScrolledText(full,wrap='none',height=12,font=('Consolas',10),background='white',foreground='#182230',padx=12,pady=10);self.output.grid(row=0,column=0,sticky='nsew');self.output.bind('<Control-a>',self.select_all)
        self.report_horizontal=ttk.Scrollbar(full,orient='horizontal',command=self.output.xview);self.report_horizontal.grid(row=1,column=0,sticky='ew');self.output.configure(xscrollcommand=self.report_horizontal.set)
        footer=ttk.Frame(self.frame);footer.grid(row=5,column=0,sticky='ew',pady=(8,6))
        self.copy_button=ttk.Button(footer,text='Copy report',command=self.copy,state='disabled');self.copy_button.pack(side='left')
        self.save_button=ttk.Menubutton(footer,text='Save report…',state='disabled');self.save_button.pack(side='left',padx=8)
        self.save_menu=tk.Menu(self.save_button,tearoff=False);self.save_button['menu']=self.save_menu
        self.save_menu.add_command(label='Save text report… (Ctrl+S)',command=self.save)
        self.save_menu.add_command(label='Save HTML report…',command=lambda:self.save('html'))
        self.save_menu.add_command(label='Compact summary — Last 5…',command=lambda:self.save('compact5'))
        self.save_menu.add_command(label='Compact summary — Last 3…',command=lambda:self.save('compact3'))
        self.recalculate_button=ttk.Button(footer,text='Recalculate',command=self.recalculate,state='disabled');self.recalculate_button.pack(side='left')
        self.open_new_button=ttk.Button(footer,text='Open new result',command=self.open_new)
        help_button=ttk.Menubutton(footer,text='Help');help_button.pack(side='right');self.help_menu=tk.Menu(help_button,tearoff=False);help_button['menu']=self.help_menu
        data_button=ttk.Menubutton(footer,text='Data & maintenance');data_button.pack(side='right',padx=8)
        self.data_menu=tk.Menu(data_button,tearoff=False);data_button['menu']=self.data_menu
        self.commands={}
        def command(menu,key,label,callback):
            menu.add_command(label=label,command=callback);self.commands[key]=(menu,menu.index('end'))
        command(self.help_menu,'instructions','Quick instructions',self.help)
        command(self.help_menu,'validation','Model validation',self.validation_dialog)
        for key,label,callback in [('update','Update datasets',lambda:self.start_operation('update')),('status','Dataset status and update details',self.maintenance_details),('recheck','Recheck recent events…',self.recheck_dialog),('restore','Restore previous datasets',self.restore)]:command(self.data_menu,key,label,callback)
        self.data_menu.add_separator()
        for key,label,callback in [('doctor','Check installation',lambda:self.start_operation('doctor')),('diagnostics','Open diagnostics',self.open_diagnostics),('rebuild','Rebuild local features',lambda:self.start_operation('rebuild')),('cache','Clear calculation cache…',self.clear_calculation_cache)]:command(self.data_menu,key,label,callback)
        self.data_menu.add_separator()
        command(self.data_menu,'import','Import from previous installation…',self.import_dialog)
        command(self.data_menu,'undo','Undo latest import…',self.undo_import)
        self.progress=ttk.Progressbar(self.frame,mode='indeterminate');self.progress.grid(row=6,column=0,sticky='ew',pady=(0,4));self.frame.rowconfigure(6,minsize=12)
        ttk.Label(self.frame,textvariable=self.status,wraplength=900).grid(row=7,column=0,sticky='w')
        self.stale=tk.StringVar();ttk.Label(self.frame,textvariable=self.stale,foreground='#725200',wraplength=900).grid(row=8,column=0,sticky='w')
        ttk.Label(self.frame,textvariable=self.freshness,style='Hint.TLabel',wraplength=900).grid(row=9,column=0,sticky='w')
        self.set_text('Enter two fighters and click Analyze, or choose Compare statistics only.\n\nPredictions train locally. Internet access is needed only for dataset updates.\n')
        for var in [self.date,*self.names.values()]:var.trace_add('write',lambda *a:self.queue_coverage())
        window.bind('<Control-s>',lambda e:self.save());window.bind('<Control-f>',self.focus_filter)
        for binding in ('<Control-plus>','<Control-equal>','<Control-KP_Add>'):window.bind(binding,lambda e:self.resize_text(1))
        for binding in ('<Control-minus>','<Control-KP_Subtract>'):window.bind(binding,lambda e:self.resize_text(-1))
        window.bind('<Configure>',self.resize)
        geometry=self.preferences.get('geometry')
        if geometry:
            try:
                w,h=map(int,geometry.split('x'));window.geometry(f'{max(720,min(w,window.winfo_screenwidth()-40))}x{max(520,min(h,window.winfo_screenheight()-80))}+20+20')
            except (ValueError,tk.TclError):pass
        else:window.geometry(f'{min(1040,window.winfo_screenwidth()-50)}x{min(820,window.winfo_screenheight()-90)}')
        if self.preferences.get('maximized'):
            try:window.state('zoomed')
            except tk.TclError:pass
        ui_scale=float(window.tk.call('tk','scaling'))/(96/72)
        window.minsize(min(round(900*ui_scale),window.winfo_screenwidth()-50),min(round(700*ui_scale),window.winfo_screenheight()-90))
        if self.collapsed:self.input_scroll.grid_remove()
        self.change_font();self.controls();self.queue_coverage()
        self.refresh_button=ttk.Button(footer,text='Refresh and compare',command=self.refresh_dialog,state='disabled');self.refresh_button.pack(side='left',padx=8)
        self.notebook.bind('<<NotebookTabChanged>>',self.tab_changed,add='+')
        if autostart:window.after(10,lambda:self.start_operation('startup'))

    def table(self,parent,row,overview=False):
        frame=ttk.Frame(parent);frame.grid(row=row,column=0,sticky='nsew');frame.columnconfigure(0,weight=1);frame.rowconfigure(0,weight=1)
        tree=ttk.Treeview(frame,columns=('metric','a','b','diff'),show='headings',selectmode='browse',height=12 if overview else 8)
        tree.configure(style=('Overview.Treeview' if overview else 'Comparison.Treeview'))
        tree.grid(row=0,column=0,sticky='nsew')
        for name,label,width in [('metric','Metric',330),('a','Fighter A',185),('b','Fighter B',185),('diff','A−B',120)]:
            tree.heading(name,text=label);tree.column(name,width=width,minwidth=90,anchor='w' if name=='metric' else 'e',stretch=True)
        vertical=ttk.Scrollbar(frame,command=tree.yview)
        if not overview:vertical.grid(row=0,column=1,sticky='ns');tree.configure(yscrollcommand=vertical.set)
        horizontal=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview);horizontal.grid(row=1,column=0,sticky='ew');tree.configure(xscrollcommand=horizontal.set)
        tree.bind('<<TreeviewSelect>>',lambda e:self.metric_details(tree));tree.bind('<Return>',lambda e:self.metric_details(tree))
        return tree

    def set_text(self,text):
        super().set_text(text)

    def toggle_inputs(self):
        self.collapsed=not self.collapsed
        self.input_scroll.grid_remove() if self.collapsed else self.input_scroll.grid()
        self.input_toggle.configure(text='Edit matchup' if self.collapsed else 'Hide inputs')
        self.controls()

    def resize(self,event):
        if event.widget is not self.window:return
        width=max(240,self.window.winfo_width()-80)
        if hasattr(self,'input_scroll'):
            available=max(80,int(self.window.winfo_height()*.28))
            self.input_scroll.canvas.configure(height=min(available,self.inputs.winfo_reqheight()))
        if hasattr(self,'title_label'):
            self.title_label.configure(wraplength=max(180,width-440))
        if hasattr(self,'recent_groups'):self.layout_recent()
        if hasattr(self,'overview_scroll'):
            for child in self.overview_scroll.content.winfo_children():
                if isinstance(child,ttk.Label):child.configure(wraplength=width-35)
        if hasattr(self,'stat_legend'):
            for label in self.stat_legend.winfo_children():label.configure(wraplength=max(150,width//2-24))
        for parent in (self.frame,self.inputs):
            for child in parent.winfo_children():
                if isinstance(child,ttk.Label):child.configure(wraplength=width)

    def change_font(self,event=None):
        points=apply_theme(self.window,self.font_size.get())
        self.output.configure(font=('Consolas',points));self.details.configure(font=('Segoe UI',points))
        for panel in getattr(self,'bout_panels',{}).values():panel.text.configure(font=('Segoe UI',points))
        if hasattr(self,'visual_panel'):
            self.visual_panel.table.configure(font=('Segoe UI',points));self.visual_panel.points=points;self.visual_panel.draw()
        if self.result:self.fill_table(self.overview_tree,overview_rows(self.result));self.render_comparison()
        if hasattr(self,'recent_groups'):self.layout_recent()
        if hasattr(self,'matchup_panel'):self.matchup_panel.layout();self.evidence_panel.layout()
        self.resize(type('Resize',(),{'widget':self.window})())

    def command_state(self,key):
        menu,index=self.commands[key];return menu.entrycget(index,'state')

    def set_command_state(self,key,state):
        menu,index=self.commands[key]
        if menu.entrycget(index,'state')!=state:menu.entryconfigure(index,state=state)

    def resize_text(self,delta):
        sizes=['Small','Medium','Large'];index=sizes.index(self.font_size.get()) if self.font_size.get() in sizes else 1
        self.font_size.set(sizes[max(0,min(2,index+delta))]);self.change_font();return 'break'

    def focus_filter(self,event=None):
        self.notebook.select(self.comparison);self.filter_entry.focus_set();return 'break'

    def select_suggestion(self,label,identity):
        sex,_=DIVISIONS[self.division.get()]
        try:self.catalogs[sex].resolve(identity[0],identity[1] if sex=='men' else None)
        except IdentityError as exc:self.errors[label].set(str(exc));return
        self.names[label].set(identity[0]);self.selection[label]=identity;self.errors[label].set('');self.queue_coverage()

    def search(self,label,event=None):
        if not self.enhanced:return super().search(label)
        if event and event.keysym in ('Up','Down','Return','Escape','Tab'):return
        if label in self.search_tasks:self.window.after_cancel(self.search_tasks[label])
        def populate():
            self.search_tasks.pop(label,None)
            sex,division=DIVISIONS[self.division.get()];catalog=self.catalogs.get(sex)
            if not catalog:return
            self.name_boxes[label]['values']=catalog.search(self.names[label].get())
            selected=self.selection.get(label)
            if selected and key(selected[0])!=key(self.names[label].get()):self.selection.pop(label,None)
            if event and len(key(self.names[label].get()))>=2 and self.window.focus_get()==self.name_boxes[label]:
                choices=catalog.suggestions(self.names[label].get())
                try:date=iso_date(self.date.get())
                except (ValueError,argparse.ArgumentTypeError):date=dt.date.today().isoformat()
                self.popups[label].show(choices,[catalog.suggestion_description(x,date,division) for x in choices])
            elif len(key(self.names[label].get()))<2:self.popups[label].hide()
        self.search_tasks[label]=self.window.after(200,populate)

    def change_division(self,event=None):
        if not self.enhanced:return super().change_division(event)
        sex,_=DIVISIONS[self.division.get()]
        if sex!=self.active_sex:
            self.category_names[self.active_sex]={label:self.names[label].get() for label in ('a','b')}
            for label in ('a','b'):self.names[label].set(self.category_names.get(sex,{}).get(label,''));self.popups[label].hide()
            self.active_sex=sex
        self.selection.clear()
        for label in ('a','b'):self.search(label)
        self.queue_coverage()

    def queue_coverage(self):
        if not self.enhanced:return
        if self.coverage_task:
            try:self.window.after_cancel(self.coverage_task)
            except tk.TclError:pass
        self.coverage_task=self.window.after(180,self.refresh_coverage)
        self.update_stale()

    def refresh_coverage(self):
        if self.coverage_task:
            try:self.window.after_cancel(self.coverage_task)
            except tk.TclError:pass
        self.coverage_task=None
        sex,division=DIVISIONS[self.division.get()];catalog=self.catalogs.get(sex)
        try:date=iso_date(self.date.get().strip());self.errors['date'].set('')
        except (ValueError,argparse.ArgumentTypeError) as exc:
            self.errors['date'].set(str(exc));self.coverage_warning.set('');return
        today=dt.date.today().isoformat();self.date_mode.set(('Historical' if date<today else 'Today' if date==today else 'Future')+' matchup · fight history excludes the selected date and later')
        warnings=[]
        for label in ('a','b'):
            if not catalog:continue
            selected=self.selection.get(label);identifier=selected[1] if selected and key(selected[0])==key(self.names[label].get()) else None
            try:identity=catalog.resolve(self.names[label].get(),identifier)
            except IdentityError:self.coverage_labels[label].set('Select a known, unambiguous fighter.');continue
            info=catalog.coverage(identity,date,division)
            self.coverage_labels[label].set(f"{info['fights']} eligible UFC fights · latest {info['latest'] or 'N/A'}\nLast division: {info['last_division'] or 'N/A'} · {info['division_fights']} in selected division")
            if not info['fights']:warnings.append(identity[0]+': no eligible UFC history')
            elif info['fights']<5:warnings.append(identity[0]+': limited recorded history')
            if not info['division_fights']:warnings.append(identity[0]+': no recorded selected-division history')
        self.coverage_warning.set('Warning: '+'; '.join(warnings) if warnings else '')

    def swap(self):
        a,b=self.names['a'].get(),self.names['b'].get();selection=dict(self.selection)
        self.names['a'].set(b);self.names['b'].set(a)
        self.selection={label:selection[other] for label,other in [('a','b'),('b','a')] if other in selection}
        self.queue_coverage()

    def prediction_request(self,workers=None):
        if not self.enhanced:return super().prediction_request(workers)
        for var in self.errors.values():var.set('')
        try:iso_date(self.date.get().strip())
        except argparse.ArgumentTypeError as exc:self.errors['date'].set(str(exc));self.date_entry.focus_set();raise
        for label in ('a','b'):
            if not self.names[label].get().strip():self.errors[label].set('Enter a fighter name.');self.name_boxes[label].focus_set();raise ValueError('Enter both fighter names.')
        try:return super().prediction_request(workers)
        except IdentityError as exc:
            sex,_=DIVISIONS[self.division.get()]
            for label in ('a','b'):
                try:self.catalogs[sex].resolve(self.names[label].get(),self.selection.get(label,('',None))[1])
                except IdentityError:self.errors[label].set(str(exc));self.name_boxes[label].focus_set();break
            raise
        except ValueError as exc:self.errors['b'].set(str(exc));self.name_boxes['b'].focus_set();raise

    def choose_identity(self,label,error,catalog):
        if self.enhanced and not error.candidates:
            self.errors[label].set(str(error));self.name_boxes[label].focus_set();return None
        return super().choose_identity(label,error,catalog)

    def analyze(self):self.run_matchup('predict')
    def compare(self):self.run_matchup('compare')

    def open_existing_comparison(self,request):
        """Navigate to an already displayed report, without a new calculation."""
        payload=self.result or {};previous=payload.get('calculation_request') or {}
        if payload.get('result_state') not in ('complete','comparison'):return False
        if previous.get('profiles_sha256'):return False
        for field in ('sex','division','fight_date','fighter_a_id','fighter_b_id','as_of_date'):
            if request.get(field)!=previous.get(field):return False
        for side in ('a','b'):
            if key(request['fighter_'+side])!=key(previous.get('fighter_'+side,'')):return False
            if not payload.get('fighter_'+side+'_comparison'):return False
        current=self.history_contexts.get(request['sex'])
        if not current or payload.get('calculation_fingerprint')!=current:return False
        date=request['fight_date'];today=dt.date.today().isoformat()
        cutoff=((dt.date.fromisoformat(date)-dt.timedelta(days=1)).isoformat() if date<=today else today) if request['sex']=='men' else date
        if previous.get('effective_cutoff')!=cutoff:return False
        self.notebook.select(self.comparison)
        self.status.set('Showing statistics from the displayed analysis. No datasets reloaded.')
        return True

    def run_matchup(self,operation):
        if self.controller.busy:return
        try:
            request=self.prediction_request()
            if not request:return
            if operation=='compare' and self.open_existing_comparison(request):return
            catalog=self.catalogs[request['sex']];warn=[]
            for side in ('a','b'):
                info=catalog.coverage((request['fighter_'+side],request['fighter_'+side+'_id']),request['fight_date'],request['division'])
                if catalog.history and (not info['fights'] or not info['division_fights']):warn.append(request['fighter_'+side]+(': no eligible UFC history' if not info['fights'] else ': no recorded selected-division history'))
            if warn and not messagebox.askyesno('Confirm hypothetical matchup','\n'.join(warn)+'\n\nContinue with this matchup? The report will include these warnings.',parent=self.window):return
            request.update(operation=operation,use_cache=self.history_setting.get());self.viewing_other=False;self.preview=None;self.new_result=None;self.open_new_button.pack_forget()
            for popup in self.popups.values():popup.hide()
            self.start(request)
        except (ValueError,OSError,argparse.ArgumentTypeError) as exc:
            self.status.set(str(exc))
            if not any(v.get() for v in self.errors.values()):messagebox.showerror('Check your matchup',str(exc),parent=self.window)

    def controls(self):
        if not getattr(self,'enhanced',False):return super().controls()
        busy=self.controller.busy;state='normal' if self.ready and not busy else 'disabled'
        for control in (self.analyze_button,self.compare_button):control.configure(state=state)
        for control in (self.date_entry,self.today_button,self.calendar_button,self.swap_button,*self.name_boxes.values()):control.configure(state='disabled' if busy else 'normal')
        self.division_box.configure(state='disabled' if busy else 'readonly')
        self.cancel_button.configure(state='normal' if busy and self.controller.cancellable else 'disabled')
        if busy:
            if not self.cancel_button.winfo_manager():self.cancel_button.pack(side='left',padx=8)
            self.operation_hint.set('Cancellation is unavailable during this stage.' if not self.controller.cancellable else '')
        else:self.cancel_button.pack_forget();self.operation_hint.set('')
        show_inputs=not self.collapsed or busy or not self.result
        for control,padding in ((self.analyze_button,0),(self.compare_button,8)):
            if show_inputs and not control.winfo_manager():control.pack(side='left',padx=padding,before=self.cancel_button if busy else None)
            elif not show_inputs:control.pack_forget()
        self.actions.grid() if show_inputs else self.actions.grid_remove()
        self.input_toggle.configure(style='Primary.TButton' if self.collapsed else 'TButton')
        self.recalculate_button.configure(state='normal' if self.result and self.result.get('calculation_request') and self.ready and not busy else 'disabled')
        if hasattr(self,'refresh_button'):self.refresh_button.configure(state='normal' if self.result and self.result.get('result_state','complete') in ('complete','comparison') and self.ready and not busy else 'disabled')
        if hasattr(self,'history_button'):self.history_button.configure(state='normal' if self.history_ready else 'disabled')
        for key in ('update','recheck','cache','import','undo'):self.set_command_state(key,state)
        for key in ('doctor','rebuild'):self.set_command_state(key,'disabled' if busy else 'normal')
        self.set_command_state('restore','normal' if self.backup_available and not busy else 'disabled')
        history_busy=busy and (self.last_request or {}).get('operation') in ('import_history','undo_import')
        if self.view_menu.entrycget('Keep recent analyses and reuse valid results','state')!=('disabled' if history_busy else 'normal'):
            self.view_menu.entryconfigure('Keep recent analyses and reuse valid results',state='disabled' if history_busy else 'normal')
        self.progress.grid() if busy else self.progress.grid_remove()
        if busy and self.pending_stage and self.pending_stage.get('total'):
            if self.progress_running:self.progress.stop();self.progress_running=False
            total=self.pending_stage['total'];self.progress.configure(mode='determinate',maximum=total,value=self.pending_stage.get('completed',0))
        elif busy and not self.progress_running:self.progress.configure(mode='indeterminate');self.progress.start(15);self.progress_running=True
        elif not busy:self.progress.stop();self.progress_running=False;self.progress.configure(mode='determinate',value=0)

    def poll(self):
        if getattr(self,'poll_id',None):
            try:self.window.after_cancel(self.poll_id)
            except tk.TclError:pass
        try:
            for event in self.controller.poll():
                if event.get('job_id') and event.get('job_id')!=getattr(self.controller,'job_id',None):continue
                if event.get('request_fingerprint') and event.get('request_fingerprint')!=getattr(self.controller,'request_fingerprint',None):continue
                if event['type']=='progress':
                    self.pending_stage=event;self.stage_message='Cancelling safely…' if getattr(self.controller,'cancel_requested',False) else event['message']
                    if event.get('target') and not self.stage_message.startswith(event['target'].title()+':') and not getattr(self.controller,'cancel_requested',False):self.stage_message=event['target'].title()+': '+self.stage_message
                    if event.get('total'):self.stage_message+=f" ({event.get('completed',0)}/{event['total']} {event.get('unit','models')} complete)"
                elif event['type']=='history_ready':
                    self.history_ready=True
                elif event['type'] in ('initial_ready','comparison_ready'):
                    self.preview=event['payload']
                    if not self.viewing_other:self.display_result(self.preview)
                else:self.pending_terminal=event
            if self.controller.busy:
                elapsed=int(time.monotonic()-self.controller.started);self.status.set(f'{self.stage_message} · {elapsed//60}:{elapsed%60:02d} elapsed')
            elif self.pending_terminal:
                event=self.pending_terminal;self.pending_terminal=None;self.handle_terminal(event)
            self.controls()
            if self.closing and not self.controller.busy:self.destroy();return
        except (OSError,ValueError,RuntimeError,tk.TclError) as exc:
            self.controller.terminate();self.status.set('Operation stopped: '+str(exc));self.controls()
        self.poll_id=self.window.after(150,self.poll)

    def handle_terminal(self,event):
        if getattr(self,'active_refresh',None) and event['type']=='error':
            if self.preview:
                self.new_result=dict(self.preview,result_state='cancelled' if event.get('code')=='cancelled' else 'failed')
                self.open_new_button.configure(text='Open partial report');self.open_new_button.pack(side='left',padx=8)
            self.active_refresh=None;self.preview=None;self.viewing_other=False
            self.status.set('Refresh '+('cancelled.' if event.get('code')=='cancelled' else 'failed: '+event.get('message','Unknown error'))+' Original report retained.')
            return
        if event['type']=='error':
            if self.preview and (self.last_request or {}).get('operation') in ('predict','compare'):
                self.preview=dict(self.preview,result_state='cancelled' if event['code']=='cancelled' else 'failed')
                if self.viewing_other:
                    self.new_result=self.preview;self.open_new_button.pack(side='left',padx=8)
                else:self.display_result(self.preview)
            if ((self.last_request or {}).get('operation') in ('update','rebuild','recover','recheck','apply_corrections') or event.get('maintenance_error')) and event.get('code')!='cancelled':
                self.last_log=event.get('log');self.status.set(event.get('message','Dataset operation could not finish.'))
                if not self.closing:self.maintenance_error_dialog(event)
                return
            return super().handle_terminal(event)
        operation=event['operation'];payload=event['payload']
        if operation=='recheck':
            self.maintenance_status=payload.get('maintenance_status',getattr(self,'maintenance_status',{}))
            self.status.set('Recheck complete. Review the captured corrections.');self.corrections_dialog(payload['preview']);return
        if operation=='clear_cache':self.status.set('Calculation cache cleared. Saved analyses retained.');return
        if operation in ('import_history','undo_import'):
            self.status.set(payload['message'])
            if 'preferences_snapshot' in payload or payload.get('preferences'):
                if 'preferences_snapshot' in payload:self.preferences=payload['preferences_snapshot']
                else:self.preferences.update(payload['preferences'])
                self.font_size.set(self.preferences.get('text_size','Medium'));self.change_font()
                if self.collapsed!=self.preferences.get('inputs_collapsed',self.collapsed):self.toggle_inputs()
                self.history_setting.set(self.preferences.get('history_enabled',True))
                if self.preferences.get('division') in DIVISIONS:
                    self.division.set(self.preferences['division']);self.change_division()
                    for side in ('a','b'):self.names[side].set(self.preferences.get('fighter_'+side,''))
                    self.queue_coverage()
                geometry=self.preferences.get('geometry')
                if geometry:
                    try:
                        w,h=map(int,geometry.split('x'));self.window.state('normal')
                        self.window.geometry(f'{max(720,min(w,self.window.winfo_screenwidth()-40))}x{max(520,min(h,self.window.winfo_screenheight()-80))}')
                    except (ValueError,tk.TclError):pass
                if self.preferences.get('maximized'):
                    try:self.window.state('zoomed')
                    except tk.TclError:pass
                self.window.update_idletasks()
                self.last_import_ui_preferences=self.preference_snapshot()
            messagebox.showinfo('Import history',payload['message'],parent=self.window);return
        if operation in ('predict','compare'):
            if self.active_refresh:
                session=self.active_refresh;self.active_refresh=None;self.preview=None
                from analyzer_refresh import captured_entry
                from analyzer_comparison import compare_entries
                try:
                    newer=self.history.load(payload['history_id']) if payload.get('history_id') else captured_entry(payload)
                    compared=compare_entries(session['original'],newer)
                except (OSError,ValueError,TypeError,KeyError) as exc:
                    self.viewing_other=False;self.new_result=payload;self.open_new_button.pack(side='left',padx=8)
                    self.status.set('Refresh complete; comparison unavailable: '+str(exc));return
                self.viewing_other=False
                if self.result is session['displayed']:
                    self.display_result(payload);self.comparison_dialog(compared)
                else:
                    self.new_result=payload;self.pending_comparison=compared
                    self.open_new_button.configure(text='Open comparison');self.open_new_button.pack(side='left',padx=8)
                    self.status.set('Refresh complete. Open comparison when ready.')
                return
            if self.viewing_other:
                self.new_result=payload;self.open_new_button.pack(side='left',padx=8);self.status.set('New analysis complete. Click Open new result.')
            else:self.display_result(payload)
            self.preview=None
            if not self.collapsed:self.toggle_inputs()
            return
        super().handle_terminal(event)
        if operation in ('startup','doctor'):self.history_ready=True
        if payload.get('catalogs'):self.catalogs={sex:FighterCatalog.from_payload(value) for sex,value in payload['catalogs'].items()}
        self.history_contexts=payload.get('calculation_fingerprints',{});self.backup_available=payload.get('backup_available',False);self.maintenance_status=payload.get('maintenance_status',{})
        self.refresh_coverage()
        if operation=='update':self.status.set('Already up to date.' if payload.get('status')=='no_changes' else 'Update complete. Use Data & maintenance → Dataset status and update details to view captured fights.')

    def display_result(self,payload):
        started=time.monotonic();self.result=payload;self.result_text=format_result(payload);self.set_text(self.result_text)
        state=payload.get('result_state','complete');title=payload['fighter_a']+' vs '+payload['fighter_b']
        self.matchup_header.set(title+' · '+str(payload.get('division',''))+' · '+payload['fight_date'])
        self.render_recent(payload)
        self.visual_panel.show(payload,render=self.notebook.select()==str(self.visual_tab))
        self.recent_form_panel.show(payload)
        self.matchup_panel.show(payload);self.evidence_panel.show(payload)
        self.comparison_scroll.canvas.yview_moveto(0)
        for side in ('a','b'):self.stat_names[side].set(side.upper()+': '+payload['fighter_'+side])
        description=self.matchup_panel.mode.get()
        self.summary.set(description)
        warnings=list(dict.fromkeys(payload.get('coverage_warnings',[])+payload.get('warnings',[])))
        self.result_warning.set('\n'.join(warnings) or 'Experimental model · review evidence and methodology limitations before interpreting the result.')
        from analyzer_summary import format_summary
        self.matchup_observations.set(format_summary(payload))
        self.overview_scroll.canvas.yview_moveto(0)
        self.summary_metrics_button.configure(state='normal' if any(x.get('metric_id') for x in payload.get('matchup_summary',{}).get('observations',[])) else 'disabled')
        self.sections=report_sections(payload);self.section_box['values']=['All sections','Summary supporting metrics']+[s['title'] for s in self.sections]
        if self.section.get() not in self.section_box['values']:self.section.set('All sections')
        self.fill_table(self.overview_tree,overview_rows(payload));self.render_comparison();self.draw_probability()
        self.copy_button.configure(state='normal');self.save_button.configure(state='normal');self.update_stale()
        self.status.set(('Saved analysis reopened.' if payload.get('reused') else 'Statistics comparison complete.' if state=='comparison' else 'Analysis complete. Copy or save the results.' if state=='complete' else description.split('\n')[0]))
        if payload.get('history_notice'):self.status.set(payload['history_notice'])
        self.last_render_seconds=time.monotonic()-started

    def fill_table(self,tree,rows):
        for item in tree.get_children():self.rows.pop((str(tree),item),None);tree.delete(item)
        if self.result:
            tree.heading('a',text=self.result['fighter_a']);tree.heading('b',text=self.result['fighter_b'])
        import textwrap
        from tkinter import font
        points={'Small':9,'Medium':10,'Large':12}.get(self.font_size.get(),10)
        character_width=max(1,font.Font(self.window,family='Segoe UI',size=points).measure('0'))
        wrap_width=max(16,int((tree.column('metric','width')-15)/character_width))
        lines=1
        for row in rows:
            label='\n'.join(textwrap.wrap(row['label'],width=wrap_width))
            lines=max(lines,label.count('\n')+1)
            item=tree.insert('','end',values=(label,row['a'],row['b'],row['difference']));self.rows[(str(tree),item)]=row
        line_height=font.Font(self.window,family='Segoe UI',size=points).metrics('linespace')
        ttk.Style(self.window).configure(tree.cget('style'),rowheight=line_height*lines+10)

    def render_comparison(self):
        if not hasattr(self,'comparison_tree'):return
        needle=key(self.filter.get());rows=[]
        summary_ids={x.get('metric_id') for x in (self.result or {}).get('matchup_summary',{}).get('observations',[])}
        summary_ids.update(x['support']['id'] for x in (self.result or {}).get('matchup_summary',{}).get('observations',[]) if x.get('support'))
        for section in getattr(self,'sections',[]):
            if self.section.get()=='Summary supporting metrics':
                rows.extend(row for row in section['rows'] if row['fields'] in summary_ids and needle in key(row['label']));continue
            if self.section.get() not in ('All sections',section['title']):continue
            rows.extend(row for row in section['rows'] if needle in key(row['label']))
        self.fill_table(self.comparison_tree,rows)

    def metric_details(self,tree):
        selected=tree.selection()
        if not selected:return
        row=self.rows.get((str(tree),selected[0]));
        if not row:return
        self.details.configure(state='normal');self.details.delete('1.0','end');self.details.insert('1.0',row['label']+'\n'+row['explanation']+'\n'+'; '.join(row['support_notes']));self.details.configure(state='disabled')
        if tree is self.overview_tree:self.notebook.select(self.comparison)

    def draw_probability(self):
        self.matchup_panel.draw()

    def update_stale(self):
        if not hasattr(self,'stale') or not self.result:return
        sex,division=DIVISIONS[self.division.get()]
        changed=any(key(self.names[side].get())!=key(self.result['fighter_'+side]) for side in ('a','b')) or self.date.get().strip()!=self.result['fight_date'] or key(division)!=key(str(self.result.get('division','')).replace("Women's ",''))
        outdated=self.result.get('calculation_fingerprint') and self.history_contexts.get(sex) and self.result['calculation_fingerprint']!=self.history_contexts[sex]
        self.stale.set('Displayed result belongs to the previous matchup. Copy and Save use the displayed result.' if changed else 'Saved result uses different datasets or app calculations; viewable but not eligible for reuse.' if outdated else '')

    def save(self,report_format='txt'):
        if not self.result:return
        compact=report_format in ('compact3','compact5')
        html_format=report_format=='html' or compact
        extension='.html' if html_format else '.txt'
        filename=Path(result_filename(self.result)).with_suffix(extension).name
        if compact:filename=Path(filename).stem+' — compact Last '+report_format[-1]+'.html'
        path=filedialog.asksaveasfilename(parent=self.window,title='Save compact summary' if compact else 'Save HTML report' if html_format else 'Save text report',initialfile=filename,initialdir=self.preferences.get('save_directory',str(Path.home()/'Documents')),defaultextension=extension,filetypes=[('HTML report','*.html')] if html_format else [('Text files','*.txt')],confirmoverwrite=True)
        if not path:return
        try:
            if compact:
                from analyzer_compact_report import compact_html
                value=compact_html(self.result,report_format[-1])
            else:value=format_html(self.result) if Path(path).suffix.lower() in ('.html','.htm') else self.result_text
            Path(path).write_text(value,encoding='utf-8',newline='\n');self.preferences['save_directory']=str(Path(path).parent);self.status.set('Results saved to '+str(path))
        except OSError as exc:messagebox.showerror('Could not save',str(exc)+'\nChoose a writable folder.',parent=self.window)

    def recalculate(self):
        if not self.result or self.controller.busy:return
        request=self.result.get('calculation_request')
        if not request:return
        if request.get('profiles_sha256'):
            messagebox.showinfo('CLI profile analysis','Recalculate this analysis through the CLI with its original manual profile file.',parent=self.window);return
        request={k:v for k,v in request.items() if k in ('operation','sex','fighter_a','fighter_b','fighter_a_id','fighter_b_id','division','fight_date','workers','as_of_date')}
        if request.get('workers')=='automatic':request.pop('workers')
        request.update(force_recalculate=True,use_cache=False);self.viewing_other=False;self.preview=None;self.start(request)

    def tab_changed(self,event=None):
        if self.notebook.select()==str(self.visual_tab) and getattr(self.visual_panel,'dirty',False):
            self.visual_panel.dirty=False;self.visual_panel.draw()

    def start(self,request):
        if self.controller.busy:return
        if request.get('operation') in ('predict','compare'):
            self.pending_comparison=None;self.new_result=None
            self.open_new_button.configure(text='Open new result');self.open_new_button.pack_forget()
        return super().start(request)

    def open_recent_form(self):
        self.notebook.select(self.comparison)
        if not self.recent_form_panel.expanded:self.recent_form_panel.toggle()
        self.window.update_idletasks()
        content=self.comparison_scroll.content
        self.comparison_scroll.canvas.yview_moveto(max(0,self.recent_form_panel.winfo_y()-12)/max(1,content.winfo_height()))
        self.recent_form_panel.toggle_button.focus_set()

    def refresh_dialog(self,entry=None):
        if self.controller.busy or not self.ready:
            self.status.set('Wait until the current operation and dataset checks finish before refreshing.');return
        from analyzer_refresh import captured_entry,refresh_request
        import copy
        try:
            if entry is None:
                if not self.result:return
                try:entry=self.history.load(self.result['history_id']) if self.result.get('history_id') else captured_entry(self.result)
                except (OSError,ValueError,KeyError):entry=captured_entry(self.result)
            entry=copy.deepcopy(entry);refresh_request(entry)
        except (ValueError,TypeError,KeyError) as exc:messagebox.showinfo('Refresh unavailable',str(exc),parent=self.window);return
        dialog=tk.Toplevel(self.window);dialog.title('Refresh and compare');dialog.transient(self.window)
        frame=ttk.Frame(dialog,padding=16);frame.pack(fill='both',expand=True)
        p=entry['payload']
        ttk.Label(frame,text=p['fighter_a']+' vs '+p['fighter_b']+'\nOriginal generated '+readable_timestamp(p.get('generated_at','')),wraplength=540).pack(anchor='w')
        use_today=tk.BooleanVar(value=False)
        ttk.Radiobutton(frame,text='Keep original matchup date: '+p['fight_date'],variable=use_today,value=False).pack(anchor='w',pady=(12,4))
        ttk.Radiobutton(frame,text="Use today's matchup date: "+dt.date.today().isoformat(),variable=use_today,value=True).pack(anchor='w')
        ttk.Label(frame,text='Uses installed datasets and the current app. Matching calculation work may be reused; a new result is captured. Dataset downloads are available separately in Data & maintenance.',wraplength=540).pack(anchor='w',pady=12)
        def begin():
            try:
                request=refresh_request(entry,use_today.get())
                catalog=self.catalogs[request['sex']]
                for side in ('a','b'):catalog.resolve(request['fighter_'+side],request['fighter_'+side+'_id'])
            except (ValueError,TypeError,KeyError) as exc:messagebox.showerror('Could not refresh',str(exc),parent=dialog);return
            if not self.result or self.result.get('history_id')!=entry.get('id'):
                self.display_result(dict(p,history_id=entry.get('id')))
            self.active_refresh=dict(original=entry,displayed=self.result)
            self.viewing_other=True;self.preview=None;self.pending_comparison=None;dialog.destroy()
            self.start(request)
            if not self.controller.busy:self.active_refresh=None;self.viewing_other=False
        buttons=ttk.Frame(frame);buttons.pack(anchor='w')
        ttk.Button(buttons,text='Refresh and compare',command=begin,style='Primary.TButton').pack(side='left')
        ttk.Button(buttons,text='Cancel',command=dialog.destroy).pack(side='left',padx=8)
        dialog.bind('<Escape>',lambda e:dialog.destroy())

    def open_new(self):
        if self.pending_comparison:
            compared=self.pending_comparison;self.pending_comparison=None
            if self.new_result:self.display_result(self.new_result)
            self.new_result=None;self.open_new_button.pack_forget();self.open_new_button.configure(text='Open new result');self.comparison_dialog(compared);return
        if self.new_result:self.viewing_other=False;self.display_result(self.new_result);self.new_result=None;self.open_new_button.pack_forget()

    def show_history(self):
        if not self.history_ready:
            self.status.set('Saved reports become available after interrupted operations are checked.');return
        dialog=tk.Toplevel(self.window);dialog.title('Recent analyses');dialog.geometry('880x430');dialog.transient(self.window)
        frame=ttk.Frame(dialog,padding=12);frame.pack(fill='both',expand=True);frame.columnconfigure(0,weight=1);frame.rowconfigure(1,weight=1)
        ttk.Label(frame,text='Completed analyses stored on this computer. Outdated results remain viewable.').grid(row=0,column=0,sticky='w')
        tree=ttk.Treeview(frame,columns=('matchup','division','date','type','created','status'),show='headings',selectmode='extended');tree.grid(row=1,column=0,sticky='nsew',pady=8)
        for column,label,width in [('matchup','Matchup',280),('division','Division',100),('date','Fight date',90),('type','Type',90),('created','Created',260),('status','Status',80)]:tree.heading(column,text=label);tree.column(column,width=width,minwidth=70)
        scrollbar=ttk.Scrollbar(frame,command=tree.yview);scrollbar.grid(row=1,column=1,sticky='ns');tree.configure(yscrollcommand=scrollbar.set)
        horizontal=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview);horizontal.grid(row=2,column=0,sticky='ew');tree.configure(xscrollcommand=horizontal.set)
        entries={}
        loading=tk.StringVar(value='Loading saved analysis metadata…')
        ttk.Label(frame,textvariable=loading).grid(row=4,column=0,sticky='w',pady=4)
        generation=[0]
        def refresh():
            tree.delete(*tree.get_children());entries.clear()
            import queue,threading
            generation[0]+=1;token=generation[0];completed=queue.Queue(maxsize=1)
            loading.set('Loading saved analysis metadata…')
            def read():
                try:completed.put((self.history.summaries(),None))
                except (OSError,ValueError,TypeError,KeyError) as exc:completed.put(([],str(exc)))
            def deliver():
                try:
                    if not dialog.winfo_exists() or generation[0]!=token:return
                    try:values,error=completed.get_nowait()
                    except queue.Empty:dialog.after(40,deliver);return
                    if error:loading.set('History unavailable: '+error);return
                    for entry in values:
                        entries[entry['id']]=entry;p=entry['payload'];sex=entry['request']['sex'];current=entry['context_fingerprint']==self.history_contexts.get(sex)
                        tree.insert('','end',iid=entry['id'],values=(p['fighter_a']+' vs '+p['fighter_b'],p.get('division',''),p['fight_date'],entry['request']['operation'],readable_timestamp(entry['created_at']),'Checking' if not self.history_contexts else 'Current' if current else 'Outdated'))
                    loading.set(str(len(values))+' saved analyses. Double-click or select Open to view a report.')
                except tk.TclError:return
            threading.Thread(target=read,daemon=True).start();dialog.after(40,deliver)
        def open_entry(event=None):
            if tree.selection():
                try:entry=self.history.load(tree.selection()[0])
                except (OSError,ValueError,KeyError,TypeError) as exc:messagebox.showerror('History unavailable',str(exc),parent=dialog);return
                self.viewing_other=self.controller.busy;self.display_result(dict(entry['payload'],history_id=entry['id']));dialog.destroy()
        def remove():
            if self.controller.busy and (self.last_request or {}).get('operation') in ('import_history','undo_import'):
                messagebox.showinfo('Import running','Wait for the history import to finish before deleting entries.',parent=dialog);return
            if tree.selection():
                try:self.history.delete(tree.selection()[0]);refresh()
                except OSError as exc:messagebox.showerror('Could not delete history',str(exc),parent=dialog)
        def clear():
            if self.controller.busy and (self.last_request or {}).get('operation') in ('import_history','undo_import'):
                messagebox.showinfo('Import running','Wait for the history import to finish before clearing history.',parent=dialog);return
            if messagebox.askyesno('Clear history','Delete all locally saved analyses?',parent=dialog):
                try:self.history.clear();refresh()
                except OSError as exc:messagebox.showerror('Could not clear history',str(exc),parent=dialog)
        buttons=ttk.Frame(frame);buttons.grid(row=3,column=0,sticky='w',pady=(8,0))
        def compare_versions():
            selected=tree.selection()
            if len(selected)!=2:messagebox.showinfo('Select two analyses','Use Ctrl+click to select two saved versions of the same matchup.',parent=dialog);return
            try:
                from analyzer_comparison import compare_entries
                pair=sorted((self.history.load(i) for i in selected),key=lambda e:e['created_at'])
                self.comparison_dialog(compare_entries(*pair))
            except ValueError as exc:messagebox.showerror('Cannot compare these analyses',str(exc),parent=dialog)
        ttk.Button(buttons,text='Compare versions',command=compare_versions).pack(side='left',padx=(0,8))
        def refresh_selected():
            if len(tree.selection())!=1:messagebox.showinfo('Select one analysis','Choose one saved analysis to refresh.',parent=dialog);return
            try:entry=self.history.load(tree.selection()[0])
            except (OSError,ValueError,TypeError,KeyError) as exc:messagebox.showerror('History unavailable',str(exc),parent=dialog);return
            dialog.destroy();self.refresh_dialog(entry)
        ttk.Button(buttons,text='Refresh and compare',command=refresh_selected).pack(side='left',padx=8)
        for label,command in [('Open',open_entry),('Delete selected',remove),('Clear history',clear),('Close',dialog.destroy)]:ttk.Button(buttons,text=label,command=command).pack(side='left',padx=(0,8))
        tree.bind('<Return>',open_entry);tree.bind('<Double-1>',open_entry);dialog.bind('<Escape>',lambda e:dialog.destroy());refresh();tree.focus_set()

    def save_history_setting(self):
        self.preferences['history_enabled']=self.history_setting.get()
        try:atomic_json(self.preferences_path,self.preferences)
        except OSError as exc:messagebox.showerror('Setting could not be saved',str(exc),parent=self.window)

    def evidence_dialog(self):
        if not self.result:return
        from analyzer_evidence import format_evidence
        dialog=tk.Toplevel(self.window);dialog.title('Evidence quality');dialog.geometry('780x480');dialog.transient(self.window)
        dialog.columnconfigure(0,weight=1);dialog.rowconfigure(0,weight=1)
        view=ScrolledText(dialog,wrap='word',font=('Segoe UI',SIZES.get(self.font_size.get(),10)));view.grid(row=0,column=0,sticky='nsew',padx=12,pady=12)
        view.insert('1.0',format_evidence(self.result));view.configure(state='disabled')
        actions=ttk.Frame(dialog);actions.grid(row=1,column=0,sticky='ew',padx=12,pady=(0,12))
        ttk.Button(actions,text='Model validation',command=self.validation_dialog).pack(side='left')
        ttk.Button(actions,text='Close',command=dialog.destroy).pack(side='right')
        dialog.bind('<Escape>',lambda event:dialog.destroy());view.focus_set()

    def validation_dialog(self):
        from analyzer_validation import load_report,format_validation
        try:text=format_validation(load_report(self.root),self.root)
        except (OSError,ValueError,KeyError) as exc:text='Validation report could not be read: '+str(exc)
        dialog=tk.Toplevel(self.window);dialog.title('Model validation');dialog.geometry('850x650');dialog.transient(self.window)
        output=ScrolledText(dialog,wrap='word',font=('Segoe UI',SIZES.get(self.font_size.get(),10)));output.pack(fill='both',expand=True,padx=12,pady=12)
        output.insert('1.0',text);output.configure(state='disabled')
        charts=self.root/'docs/MODEL_VALIDATION.html'
        if charts.is_file():
            import webbrowser
            ttk.Button(dialog,text='Open calibration charts (offline)',command=lambda:webbrowser.open(charts.resolve().as_uri())).pack(pady=(0,8))
        ttk.Button(dialog,text='Close',command=dialog.destroy).pack(pady=(0,12))

    def import_dialog(self):
        if self.controller.busy:return
        folder=filedialog.askdirectory(parent=self.window,title='Choose the previous extracted app folder')
        if not folder:return
        from analyzer_migration import preview
        try:
            self.preferences=self.preference_snapshot();atomic_json(self.preferences_path,self.preferences)
            value=preview(self.root,folder)
        except (OSError,ValueError,TypeError) as exc:messagebox.showerror('Import could not be reviewed',str(exc),parent=self.window);return
        dialog=tk.Toplevel(self.window);dialog.title('Review previous analyses');dialog.geometry('780x500');dialog.transient(self.window)
        output=ScrolledText(dialog,wrap='word',font=('Segoe UI',SIZES.get(self.font_size.get(),10)));output.pack(fill='both',expand=True,padx=12,pady=12)
        counts=value['counts'];output.insert('1.0','Ready to import: '+str(counts['valid'])+'\n'+', '.join(k+': '+str(v) for k,v in counts.items() if k!='valid')+'\n\n')
        for row in value['rows']:output.insert('end',row['name']+' — '+row['status']+(' — '+row['reason'] if row.get('reason') else '')+'\n')
        output.configure(state='disabled');prefs=tk.BooleanVar(value=False)
        selection=ttk.Treeview(dialog,columns=('matchup','status'),show='headings',selectmode='extended',height=5)
        selection.heading('matchup',text='Choose incoming analyses (Ctrl+click)');selection.heading('status',text='Preview status')
        selection.column('matchup',width=490);selection.column('status',width=160);selection.pack(fill='x',padx=12)
        for row in value['rows']:
            if row.get('entry'):
                payload=row['entry']['payload'];identity=row['name'][:-5]
                selection.insert('','end',iid=identity,values=(payload['fighter_a']+' vs '+payload['fighter_b']+' · '+payload['fight_date'],row['status']))
                if row['status']=='valid':selection.selection_add(identity)
        ttk.Checkbutton(dialog,text='Also import text size, window size and collapsed-input preference',variable=prefs).pack(anchor='w',padx=12)
        ttk.Label(dialog,text='Existing analyses stay in place. Original installation is read-only. Close the older app before importing.').pack(anchor='w',padx=12,pady=8)
        def apply_import():
            request=dict(operation='import_history',preview_id=value['id'],import_preferences=prefs.get(),selected_ids=list(selection.selection()));dialog.destroy();self.start(request)
        ttk.Button(dialog,text='Import reviewed analyses',command=apply_import).pack(side='left',padx=12,pady=12)
        ttk.Button(dialog,text='Cancel',command=dialog.destroy).pack(side='right',padx=12,pady=12)

    def undo_import(self):
        if self.controller.busy:return
        if messagebox.askyesno('Undo latest import','Remove entries from the latest import and restore its preferences when they have not changed?',parent=self.window):
            current=self.preference_snapshot()
            try:
                if current!=getattr(self,'last_import_ui_preferences',None):
                    atomic_json(self.preferences_path,current);self.preferences=current
            except OSError as exc:messagebox.showerror('Undo could not start',str(exc),parent=self.window);return
            self.start(dict(operation='undo_import'))

    def preference_snapshot(self):
        return dict(self.preferences,division=self.division.get(),fighter_a=self.names['a'].get(),fighter_b=self.names['b'].get(),
                    category_names=dict(self.category_names),inputs_collapsed=self.collapsed,text_size=self.font_size.get(),
                    history_enabled=self.history_setting.get(),maximized=self.window.state()=='zoomed',
                    geometry=f'{self.window.winfo_width()}x{self.window.winfo_height()}')

    def summary_metrics(self):
        self.notebook.select(self.comparison);self.section.set('Summary supporting metrics');self.filter.set('');self.render_comparison()
        ids={x.get('metric_id') for x in (self.result or {}).get('matchup_summary',{}).get('observations',[])}
        ids.update(x['support']['id'] for x in (self.result or {}).get('matchup_summary',{}).get('observations',[]) if x.get('support'))
        items=[item for item in self.comparison_tree.get_children() if self.rows.get((str(self.comparison_tree),item),{}).get('fields') in ids]
        if items:self.comparison_tree.selection_set(items[0]);self.comparison_tree.see(items[0]);self.metric_details(self.comparison_tree)

    def clear_calculation_cache(self):
        if self.controller.busy:return
        from analyzer_cache import cache_size
        size=cache_size(self.root)/1048576
        if messagebox.askyesno('Clear calculation cache',f'Clear {size:.1f} MiB of prepared calculations? Saved analyses and datasets are retained.',parent=self.window):self.start(dict(operation='clear_cache'))

    def recheck_dialog(self):
        if self.controller.busy:return
        dialog=tk.Toplevel(self.window);dialog.title('Recheck recorded events');dialog.transient(self.window)
        frame=ttk.Frame(dialog,padding=16);frame.pack(fill='both',expand=True)
        start=tk.StringVar(value=(dt.date.today()-dt.timedelta(days=90)).isoformat());end=tk.StringVar(value=dt.date.today().isoformat())
        ttk.Label(frame,text='Re-fetch completed events and preview corrections. Maximum 20 events.').pack(anchor='w')
        for label,var in (('From date (inclusive)',start),('To date (inclusive)',end)):
            ttk.Label(frame,text=label).pack(anchor='w',pady=(8,0));ttk.Entry(frame,textvariable=var).pack(fill='x')
        error=tk.StringVar();ttk.Label(frame,textvariable=error,foreground='#a12622').pack(anchor='w')
        def run():
            try:
                a,b=iso_date(start.get()),iso_date(end.get())
                if a>b or b>dt.date.today().isoformat():raise ValueError('Choose an ordered range ending no later than today.')
                dialog.destroy();self.start(dict(operation='recheck',from_date=a,to_date=b))
            except (ValueError,argparse.ArgumentTypeError) as exc:error.set(str(exc))
        ttk.Button(frame,text='Recheck and preview',command=run).pack(pady=10)

    def corrections_dialog(self,value):
        dialog=tk.Toplevel(self.window);dialog.title('Review recorded-fight corrections');dialog.geometry('900x560');dialog.transient(self.window)
        text=ScrolledText(dialog,wrap='word',padx=12,pady=12);text.pack(fill='both',expand=True)
        lines=['Checked '+value['start']+' through '+value['end'],'Preview captured: '+readable_timestamp(value['created_at'])]
        for sex,capture in value['captures'].items():
            lines+=['',sex.title()+' events:']+[e['event_date']+' '+e['event_name'] for e in capture['events']]
        for c in value['changes']:
            rows=[r for r in value['captures'][c['sex']]['tables'][c['path']] if r['fight_id']==c['fight_id']]
            lines+=['',c['sex'].title()+' '+c['fight_id']+' ('+c['kind']+')']
            if rows:
                event=next((e for e in value['captures'][c['sex']]['events'] if e.get('event_id')==rows[0].get('event_id') or e['event_date']==rows[0]['event_date'][:10]),{})
                names=[r.get('fighter_name',r.get('fighter','')) for r in rows]
                lines += [event.get('event_date',rows[0]['event_date'][:10])+' '+event.get('event_name',rows[0].get('event_name','')),' vs '.join(n for n in names if n)]
            lines += [str(d['identity'])+' / '+d['field']+': '+str(d['before'])+' → '+str(d['after']) for d in c['differences']]
        if value['changes']:lines+=['','Applying replaces the captured complete bout records and rebuilds affected history. Draw/no-contest records retain their statistics and are excluded from binary training.']
        if not value['changes']:lines+=['','No source differences found. Installed datasets are unchanged.']
        text.insert('1.0','\n'.join(lines));text.configure(state='disabled')
        buttons=ttk.Frame(dialog);buttons.pack(pady=8)
        def apply():
            if self.controller.busy:return
            dialog.destroy();self.start(dict(operation='apply_corrections',preview_id=value['id']))
        if value['changes']:ttk.Button(buttons,text='Apply captured corrections',command=apply).pack(side='left',padx=8)
        ttk.Button(buttons,text='Close',command=dialog.destroy).pack(side='left',padx=8)

    def comparison_dialog(self,value):
        from analyzer_comparison import format_comparison,comparison_html
        dialog=tk.Toplevel(self.window);dialog.title('Compare saved versions');dialog.geometry('900x600');dialog.transient(self.window)
        text=ScrolledText(dialog,wrap='word',padx=12,pady=12);text.pack(fill='both',expand=True)
        report=format_comparison(value);text.insert('1.0',report);text.configure(state='disabled')
        buttons=ttk.Frame(dialog);buttons.pack(pady=8)
        def save(kind):
            path=filedialog.asksaveasfilename(parent=dialog,initialfile='Matchup comparison.'+kind,defaultextension='.'+kind,filetypes=[(kind.upper(),'*.'+kind)])
            if path:
                try:Path(path).write_text(comparison_html(value) if kind=='html' else report,encoding='utf-8')
                except OSError as exc:messagebox.showerror('Could not save',str(exc),parent=dialog)
        def open_report(which):
            self.viewing_other=self.controller.busy;self.display_result(value[which]['payload'])
        for label,command in [('Open original',lambda:open_report('original')),('Open newer',lambda:open_report('newer')),('Save TXT',lambda:save('txt')),('Save HTML',lambda:save('html')),('Close',dialog.destroy)]:ttk.Button(buttons,text=label,command=command).pack(side='left',padx=6)

    def maintenance_details(self):
        status=getattr(self,'maintenance_status',{})
        text=self.freshness.get()+'\n\nLast successful update check: '+status.get('last_successful_check','Never')+'\nLast successful data change: '+status.get('last_successful_change','Bundled snapshot')+'\nBackup available: '+('Yes' if self.backup_available else 'No')
        if status.get('last_recheck'):
            checked=status.get('recheck_range',{})
            text+='\nLast event recheck: '+status['last_recheck']+' ('+checked.get('start','')+' through '+checked.get('end','')+')'
        if status.get('last_operation'):
            text+='\n\nLast operation: '+status['last_operation']+' · '+status.get('transaction_status','')+'\n'+status.get('stages','')
            for sex,value in status.get('summary',{}).items():
                text+='\n\n'+sex.title()+': '+str(value.get('added_fights',0))+' added fights'
                for field,label in [('events_inspected','Events inspected'),('decisive_fights','Decisive bouts'),('draws','Draws'),('no_contests','No contests'),('corrected_fights','Corrected bouts'),('binary_training_rows_added','Binary training rows added'),('binary_training_rows_removed','Binary training rows removed'),('binary_training_rows_net','Binary training row net change'),('data_through','Data through')]:
                    if field in value:text+='\n'+label+': '+str(value[field])
        dialog=tk.Toplevel(self.window);dialog.title('Dataset status and update details');dialog.geometry('650x380');dialog.transient(self.window)
        details=ScrolledText(dialog,wrap='word',font=('Segoe UI',SIZES.get(self.font_size.get(),10)),padx=12,pady=12)
        details.pack(fill='both',expand=True);details.insert('1.0',text);details.configure(state='disabled')
        buttons=ttk.Frame(dialog);buttons.pack(pady=8)
        if status.get('last_changed_transaction') or status.get('transaction'):
            ttk.Button(buttons,text='View updated fights',command=self.updated_fights_dialog).pack(side='left',padx=8)
        ttk.Button(buttons,text='Close',command=dialog.destroy).pack(side='left',padx=8)
        dialog.bind('<Escape>',lambda event:dialog.destroy())

    def build_recent_tab(self):
        self.recent_tab.columnconfigure(0,weight=1);self.recent_tab.rowconfigure(1,weight=1)
        self.recent_caption=tk.StringVar(value='Analyze or compare a matchup to see recent fights.')
        ttk.Label(self.recent_tab,textvariable=self.recent_caption,wraplength=900).grid(row=0,column=0,sticky='w',pady=(0,8))
        self.recent_canvas=tk.Canvas(self.recent_tab,highlightthickness=0)
        self.recent_canvas.grid(row=1,column=0,sticky='nsew')
        scroll=ttk.Scrollbar(self.recent_tab,orient='vertical',command=self.recent_canvas.yview);scroll.grid(row=1,column=1,sticky='ns');self.recent_canvas.configure(yscrollcommand=scroll.set)
        self.recent_holder=ttk.Frame(self.recent_canvas);self.recent_window=self.recent_canvas.create_window((0,0),window=self.recent_holder,anchor='nw')
        self.recent_holder.bind('<Configure>',lambda e:self.recent_canvas.configure(scrollregion=self.recent_canvas.bbox('all')))
        self.recent_canvas.bind('<Configure>',lambda e:(self.recent_canvas.itemconfigure(self.recent_window,width=e.width),self.layout_recent()))
        self.recent_groups={};self.recent_trees={};self.recent_notes={};self.recent_titles={};self.bout_panels={}
        for side in ('fighter_a','fighter_b'):
            group=ttk.Frame(self.recent_holder,padding=(0,0,8,8));group.columnconfigure(0,weight=1)
            title=tk.StringVar(value=side.replace('_',' ').title());self.recent_titles[side]=title
            ttk.Label(group,textvariable=title).grid(row=0,column=0,sticky='w',pady=(0,4))
            tree=ttk.Treeview(group,columns=('date','opponent','result','division','method'),show='headings',height=5)
            for field,label,width in [('date','Date',90),('opponent','Opponent',140),('result','Result',90),('division','Division',110),('method','Method',100)]:
                tree.heading(field,text=label);tree.column(field,width=width,minwidth=width,stretch=True)
            tree.grid(row=1,column=0,sticky='ew')
            horizontal=ttk.Scrollbar(group,orient='horizontal',command=tree.xview);horizontal.grid(row=2,column=0,sticky='ew');tree.configure(xscrollcommand=horizontal.set)
            note=tk.StringVar(value='No analysis selected.');self.recent_notes[side]=note
            ttk.Label(group,textvariable=note,wraplength=460).grid(row=3,column=0,sticky='w',pady=6)
            from analyzer_context_widgets import BoutDetails
            panel=BoutDetails(group);panel.grid(row=4,column=0,sticky='ew');self.bout_panels[side]=panel
            tree.bind('<Return>',lambda e,side=side:self.toggle_bout(side))
            tree.bind('<Double-1>',lambda e,side=side:self.toggle_bout(side))
            tree.bind('<<TreeviewSelect>>',lambda e,side=side:self.recent_selection(side))
            tree.bind('<FocusIn>',lambda e,side=side:self.recent_focus(side))
            tree.bind('<MouseWheel>',self.recent_scroll)
            self.recent_groups[side]=group;self.recent_trees[side]=tree
        self.layout_recent()

    def recent_scroll(self,event):
        region=self.recent_canvas.bbox('all')
        if region and region[3]>self.recent_canvas.winfo_height():
            self.recent_canvas.yview_scroll(-int(event.delta/120),'units');return 'break'

    def recent_focus(self,side):
        region=self.recent_canvas.bbox('all')
        if region and region[3]>self.recent_canvas.winfo_height():
            self.recent_canvas.yview_moveto(self.recent_groups[side].winfo_y()/max(1,region[3]))

    def layout_recent(self):
        wide=self.window.winfo_width() >= (1300 if self.font_size.get()=='Large' else 1100)
        for i,side in enumerate(('fighter_a','fighter_b')):
            self.recent_groups[side].grid(row=0 if wide else i,column=i if wide else 0,sticky='nsew')
            for widget in self.recent_groups[side].winfo_children():
                if isinstance(widget,ttk.Label):widget.configure(wraplength=max(260,(self.window.winfo_width()-100)//(2 if wide else 1)))
        self.recent_holder.columnconfigure(0,weight=1);self.recent_holder.columnconfigure(1,weight=1 if wide else 0)

    def render_recent(self,payload):
        history=payload.get('recent_fights')
        self.recent_caption.set('Last five recorded UFC bouts before '+history['history_cutoff']+' · all divisions · installed source snapshot' if history else OLD_HISTORY_MESSAGE)
        for side in ('fighter_a','fighter_b'):
            tree=self.recent_trees[side];tree.delete(*tree.get_children())
            rows=history.get(side,[]) if history else []
            self.recent_titles[side].set(payload[side]+f' · {len(rows)} recorded bouts' if history else payload[side])
            for i,row in enumerate(rows):tree.insert('','end',iid=str(i),values=display_row(row))
            self.recent_notes[side].set('Select a bout to see event, round and time.' if rows else 'No eligible recorded UFC fights before this date.' if history else OLD_HISTORY_MESSAGE)
            message='Bout details will be captured when this analysis finishes.' if payload.get('result_state')=='pending' or payload.get('quick_comparison') else 'Bout details were not captured before this operation stopped. Run a new analysis to include them.' if payload.get('result_state') in ('failed','cancelled') else 'Not recorded in this saved analysis. Refresh to capture these details.'
            self.bout_panels[side].reset(message);self.bout_panels[side].button.configure(state='disabled')

    def recent_selection(self,side):
        selection=self.recent_trees[side].selection()
        if not selection or not self.result:return
        rows=self.result.get('recent_fights',{}).get(side,[])
        if int(selection[0])>=len(rows):return
        row=rows[int(selection[0])]
        _,opponent,result,division,method=display_row(row)
        self.recent_notes[side].set(opponent+' · '+result+' · '+division+' · '+method+'\nEvent: '+str(row.get('event_name') or 'N/A')+' · Round: '+str(row.get('round') or 'N/A')+' · Time: '+str(row.get('time') or 'N/A'))
        bouts=self.result.get('bout_details',{}).get(side,{}).get('bouts',[])
        self.bout_panels[side].button.configure(state='normal')
        self.bout_panels[side].show(next((b for b in bouts if b['fight_id']==row['fight_id']),None))

    def toggle_bout(self,side):
        if not self.recent_trees[side].selection():return 'break'
        self.recent_selection(side);return self.bout_panels[side].toggle()

    def maintenance_error_dialog(self,event):
        error=dict(event.get('maintenance_error') or {})
        error.setdefault('title','Dataset operation could not finish');error.setdefault('message',event.get('message','Unknown failure'))
        error.setdefault('next_step','Open details for the diagnostic log.');error.setdefault('diagnostics_path',event.get('log',''))
        if error.get('installation_state')=='recovery_required':self.ready=False
        dialog=tk.Toplevel(self.window);dialog.title(error['title']);dialog.transient(self.window);dialog.geometry('660x380')
        text=error['message']
        if error.get('event_name'):text+='\n\nEvent: '+error['event_name']
        names=[error.get('fighter_a'),error.get('fighter_b')]
        if any(names):text+='\nFight: '+' vs '.join(x or 'Unknown fighter' for x in names)
        text+='\n\n'+error['next_step']+'\n\n'+STATES.get(error.get('installation_state'),'Open details to check the transaction state.')
        details=ScrolledText(dialog,wrap='word',font=('Segoe UI',SIZES.get(self.font_size.get(),10)),padx=12,pady=12);details.pack(fill='both',expand=True);details.insert('1.0',text);details.configure(state='disabled')
        buttons=ttk.Frame(dialog,padding=10);buttons.pack(fill='x')
        request=dict(self.last_request or {})
        def retry():
            if self.controller.busy:return
            dialog.destroy();self.window.after_idle(lambda:self.start(request))
        if error.get('retryable') and error.get('installation_state') in ('unchanged','rolled_back'):
            ttk.Button(buttons,text='Retry',command=retry).pack(side='left',padx=(0,8))
        def view():
            path=Path(error.get('diagnostics_path') or '')
            if path.is_file() or path.is_dir():os.startfile(path)
            else:messagebox.showinfo('Details unavailable','This diagnostic file is no longer available. Use Data & maintenance → Open diagnostics.',parent=dialog)
        ttk.Button(buttons,text='View details',command=view).pack(side='left',padx=(0,8))
        def copy():
            self.window.clipboard_clear();self.window.clipboard_append(diagnostic_text(error,VERSION))
        ttk.Button(buttons,text='Copy diagnostics',command=copy).pack(side='left',padx=(0,8))
        close=ttk.Button(buttons,text='Close',command=dialog.destroy);close.pack(side='right');close.focus_set()
        dialog.bind('<Escape>',lambda e:dialog.destroy())

    def updated_fights_dialog(self):
        status=getattr(self,'maintenance_status',{});transaction=status.get('last_changed_transaction') or status.get('transaction')
        if not transaction or Path(transaction).name!=transaction:return
        base=self.root/'.runtime/transactions'/transaction
        rows=[]
        for sex in ('men','women'):
            try:
                value=json.loads((base/'audits'/sex/'captured_fights.json').read_text(encoding='utf-8'))
                rows.extend((sex,row) for row in value['fights'])
            except (OSError,ValueError,KeyError):pass
        dialog=tk.Toplevel(self.window);dialog.title('Updated fights');dialog.geometry('1000x480');dialog.transient(self.window)
        try:transaction_state=json.loads((base/'journal.json').read_text(encoding='utf-8')).get('status','Unknown')
        except (OSError,ValueError):transaction_state='Details unavailable'
        caption='Captured fights · transaction '+transaction+' · '+transaction_state if rows else 'No newly captured fights, or the detailed audit is no longer available.'
        ttk.Label(dialog,text=caption,padding=10).pack(anchor='w')
        columns=('date','event','fighters','outcome','training')
        tree=ttk.Treeview(dialog,columns=columns,show='headings')
        for col,label,width in [('date','Date',95),('event','Event',270),('fighters','Fighters',300),('outcome','Outcome',100),('training','Binary training',110)]:tree.heading(col,text=label);tree.column(col,width=width,minwidth=width)
        tree.pack(fill='both',expand=True,padx=10)
        for sex,row in rows:
            outcome={'win_loss':'Decisive','draw':'Draw','nc':'No contest','no_contest':'No contest'}.get(row.get('outcome'),'N/A')
            tree.insert('','end',values=(row.get('event_date'),row.get('event_name'),row.get('fighter_1','')+' vs '+row.get('fighter_2',''),outcome,'Eligible' if row.get('training_eligible')=='True' else 'Excluded'))
        ttk.Button(dialog,text='Close',command=dialog.destroy).pack(pady=10);dialog.bind('<Escape>',lambda e:dialog.destroy())

    def help(self):
        messagebox.showinfo('Quick instructions','Choose a division, date and two fighters. Suggestions appear as you type.\n\nAnalyze prepares statistics and then trains locally; Compare statistics only skips prediction training. Read Overview, browse Statistics and Charts, or open the complete Report.\n\nCopy and Save include the complete displayed report. Save supports TXT and offline HTML. Recent analyses keeps the latest 50 completed results and reuses identical valid results. Recalculate bypasses saved results and the calculation cache.\n\nDataset updates need internet. Use Data & maintenance for updates, status, diagnostics, rebuild and recovery. View contains text size and history preferences.\n\nKeyboard: Ctrl+Enter analyzes; Ctrl+S saves; Ctrl+Shift+C copies; Ctrl+F finds a metric; Ctrl+Plus/Minus changes text size.',parent=self.window)

    def destroy(self):
        if getattr(self,'enhanced',False):
            self.progress.stop()
            self.category_names[self.active_sex]={label:self.names[label].get() for label in ('a','b')}
            self.preferences.update(category_names=self.category_names,inputs_collapsed=self.collapsed,text_size=self.font_size.get(),history_enabled=self.history_setting.get(),maximized=self.window.state()=='zoomed',geometry=f'{self.window.winfo_width()}x{self.window.winfo_height()}')
            for popup in self.popups.values():popup.hide()
            for task in [*self.search_tasks.values(),self.coverage_task]:
                if task:
                    try:self.window.after_cancel(task)
                    except tk.TclError:pass
        super().destroy()

def main():
    parser=argparse.ArgumentParser(description='UFC Matchup Analyzer desktop interface')
    parser.add_argument('--smoke-report',type=Path,help=argparse.SUPPRESS)
    args=parser.parse_args()
    enable_dpi_awareness()
    window=tk.Tk()
    smoke_exit=[0]
    dialogs=[]
    if args.smoke_report:
        # An unattended launcher verification still constructs the real window and
        # performs real installation checks. No checks are mocked or bypassed.
        messagebox.showinfo=lambda *a,**k:dialogs.append(str(a))
        messagebox.showerror=lambda *a,**k:dialogs.append(str(a))
    try:
        app=AnalyzerApp(window)
        if args.smoke_report:
            started=time.monotonic()
            def finish_smoke():
                if app.controller.busy and time.monotonic()-started<90:
                    window.after(150,finish_smoke);return
                report=dict(ready=app.ready,version=VERSION,python=sys.version.split()[0],executable=sys.executable,search_paths=sys.path,tcl=window.tk.call('info','patchlevel'),tk=window.tk.call('package','provide','Tk'),window_title=window.title(),window_size=[window.winfo_width(),window.winfo_height()],status=app.status.get(),freshness=app.freshness.get(),seconds=round(time.monotonic()-started,2),dialogs=dialogs)
                atomic_json(args.smoke_report,report)
                if app.controller.busy:app.controller.terminate()
                smoke_exit[0]=0 if app.ready else 1
                app.destroy()
            window.after(300,finish_smoke)
        window.mainloop()
    except BaseException as exc:
        try:messagebox.showerror('UFC Matchup Analyzer',str(exc)+'\n\nExtract the complete ZIP into a writable folder.',parent=window)
        except tk.TclError:pass
        return 1
    return smoke_exit[0]

if __name__=='__main__':raise SystemExit(main())
