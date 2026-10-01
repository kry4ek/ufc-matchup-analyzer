"""Small dependency-free native calendar and keyboard suggestion popup."""
from __future__ import annotations
import calendar
import datetime as dt
import tkinter as tk
from tkinter import ttk

class CalendarDialog:
    def __init__(self, parent, value, choose):
        try:self.date=dt.date.fromisoformat(value)
        except ValueError:self.date=dt.date.today()
        self.choose=choose;self.window=tk.Toplevel(parent);self.window.title('Choose fight date')
        self.window.transient(parent);self.window.grab_set();self.window.resizable(False,False)
        self.frame=ttk.Frame(self.window,padding=12);self.frame.pack(fill='both',expand=True)
        self.window.bind('<Escape>',lambda e:self.window.destroy())
        self.window.bind('<Prior>',lambda e:self.move(-1));self.window.bind('<Next>',lambda e:self.move(1))
        self.draw()

    def move(self, months):
        year,month=divmod(self.date.year*12+self.date.month-1+months,12)
        if 1<=year<=9999:self.date=dt.date(year,month+1,1);self.draw()

    def draw(self):
        for child in self.frame.winfo_children():child.destroy()
        ttk.Button(self.frame,text='‹ Previous',command=lambda:self.move(-1)).grid(row=0,column=0,columnspan=2)
        ttk.Label(self.frame,text=self.date.strftime('%B %Y')).grid(row=0,column=2,columnspan=3,padx=6)
        ttk.Button(self.frame,text='Next ›',command=lambda:self.move(1)).grid(row=0,column=5,columnspan=2)
        for col,day in enumerate(calendar.day_abbr):ttk.Label(self.frame,text=day,padding=5).grid(row=1,column=col)
        buttons=[]
        for row,week in enumerate(calendar.monthcalendar(self.date.year,self.date.month),2):
            for col,day in enumerate(week):
                if not day:continue
                date=dt.date(self.date.year,self.date.month,day)
                def accept(date=date):self.choose(date.isoformat());self.window.destroy()
                button=ttk.Button(self.frame,text=str(day),width=4,command=accept);button.grid(row=row,column=col,pady=2);buttons.append(button)
                button.bind('<Left>',lambda e,b=button:self.step(b,-1));button.bind('<Right>',lambda e,b=button:self.step(b,1))
                button.bind('<Up>',lambda e,b=button:self.step(b,-7));button.bind('<Down>',lambda e,b=button:self.step(b,7))
                if day==self.date.day:button.focus_set()
        self.buttons=buttons
        ttk.Label(self.frame,text='Arrow keys select days · Page Up/Down change month').grid(row=9,column=0,columnspan=7,pady=(8,0))

    def step(self,button,delta):
        index=self.buttons.index(button)+delta
        if 0<=index<len(self.buttons):self.buttons[index].focus_set()
        return 'break'

class SuggestPopup:
    def __init__(self,entry,on_select):
        self.entry=entry;self.on_select=on_select;self.window=None;self.choices=[]
        entry.bind('<Down>',self.down,add='+');entry.bind('<Up>',self.up,add='+')
        entry.bind('<Return>',self.accept,add='+');entry.bind('<Escape>',self.hide,add='+')
        entry.bind('<FocusOut>',lambda e:entry.after(150,self.hide),add='+')

    def show(self,choices,labels):
        self.hide();self.choices=list(choices)
        if not self.entry.winfo_viewable():return
        self.window=tk.Toplevel(self.entry);self.window.overrideredirect(True)
        self.list=tk.Listbox(self.window,height=max(1,min(7,len(labels))),exportselection=False,font=('Segoe UI',10),activestyle='dotbox')
        self.list.pack(fill='both',expand=True)
        for label in labels or ['No matching fighter']:self.list.insert('end',label)
        width=max(self.entry.winfo_width(),min(680,self.entry.winfo_screenwidth()-50))
        x=min(self.entry.winfo_rootx(),self.entry.winfo_screenwidth()-width-10)
        y=self.entry.winfo_rooty()+self.entry.winfo_height()
        self.window.update_idletasks();height=self.list.winfo_reqheight()
        if y+height>self.entry.winfo_screenheight()-30:y=self.entry.winfo_rooty()-height
        self.window.geometry(f'{width}x{height}+{max(0,x)}+{max(0,y)}')
        self.list.bind('<ButtonRelease-1>',self.accept)

    def down(self,event=None):return self.navigate(1)
    def up(self,event=None):return self.navigate(-1)
    def navigate(self,delta):
        if self.window and self.choices:
            selected=self.list.curselection();index=max(0,min(len(self.choices)-1,(selected[0] if selected else -1)+delta))
            self.list.selection_clear(0,'end');self.list.selection_set(index);self.list.see(index)
            return 'break'

    def accept(self,event=None):
        if self.window and self.choices:
            selection=self.list.curselection()
            if selection:self.on_select(self.choices[selection[0]]);self.hide();return 'break'

    def hide(self,event=None):
        if self.window:
            try:self.window.destroy()
            except tk.TclError:pass
        self.window=None
        if event:return 'break'
