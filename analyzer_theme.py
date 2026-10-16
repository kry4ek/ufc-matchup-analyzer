"""Shared native UI presentation; independent of calculation and saved data."""
import datetime as dt

COLORS = dict(background='#f1f4f8', surface='#ffffff', text='#182b3a',
              muted='#506273', border='#d5dde6', primary='#195a88',
              fighter_a='#246b9b', fighter_b='#9c4f21', warning='#775314',
              error='#a12622', selection='#dcecf8')
SIZES = {'Small': 9, 'Medium': 10, 'Large': 12}


def readable_timestamp(value):
    if not value:
        return 'Not recorded'
    try:
        stamp = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return 'Unavailable (unrecognized timestamp)'
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        return stamp.strftime('%d %b %Y, %H:%M') + ' (timezone not recorded)'
    local = stamp.astimezone()
    offset = local.strftime('%z')
    return local.strftime('%d %b %Y, %H:%M') + f' (UTC{offset[:3]}:{offset[3:]})'


def apply_theme(window, size='Medium'):
    from tkinter import ttk, font
    points = SIZES.get(size, 10)
    style = ttk.Style(window)
    # Clam renders color/state maps consistently; Vista ignores button fills.
    if style.theme_use() != 'clam':
        style.theme_use('clam')
    for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont'):
        font.nametofont(name, root=window).configure(family='Segoe UI', size=points)
    window.configure(background=COLORS['background'])
    style.configure('.', font=('Segoe UI', points), background=COLORS['background'], foreground=COLORS['text'])
    style.configure('TFrame', background=COLORS['background'])
    style.configure('TLabel', background=COLORS['background'], foreground=COLORS['text'])
    style.configure('Surface.TFrame', background=COLORS['surface'])
    style.configure('Surface.TLabel', background=COLORS['surface'])
    style.configure('Title.TLabel', font=('Segoe UI', points+7, 'bold'))
    style.configure('Section.TLabel', font=('Segoe UI', points+1, 'bold'), background=COLORS['surface'])
    style.configure('Hint.TLabel', foreground=COLORS['muted'])
    style.configure('Caption.TLabel', foreground=COLORS['muted'], background=COLORS['surface'])
    style.configure('Warning.TLabel', foreground=COLORS['warning'], background=COLORS['surface'])
    for side in ('a', 'b'):
        style.configure(f'Fighter{side.upper()}.TLabel', foreground=COLORS['fighter_'+side],
                        background=COLORS['surface'], font=('Segoe UI', points+3, 'bold'))
        style.configure(f'Probability{side.upper()}.TLabel', foreground=COLORS['fighter_'+side],
                        background=COLORS['surface'], font=('Segoe UI', points+13, 'bold'))
    style.configure('TButton', padding=(12, 7), borderwidth=1, relief='flat')
    style.configure('TMenubutton', padding=(12, 7), relief='flat')
    style.configure('Primary.TButton', background=COLORS['primary'], foreground='white')
    style.map('Primary.TButton', background=[('disabled', '#d5dde6'), ('pressed', '#123e60'), ('active', '#174c74')],
              foreground=[('disabled', '#506273'), ('!disabled', 'white')])
    style.map('TButton', bordercolor=[('focus', COLORS['primary'])], background=[('active', '#e0e9f2')])
    style.configure('TEntry', padding=5, fieldbackground='white')
    style.configure('TCombobox', padding=5, fieldbackground='white')
    style.configure('TNotebook', background=COLORS['background'], borderwidth=0)
    style.configure('TNotebook.Tab', padding=(14, 9))
    style.map('TNotebook.Tab', background=[('selected', 'white')], foreground=[('selected', COLORS['primary'])])
    height = font.Font(window, family='Segoe UI', size=points).metrics('linespace') + 10
    for name in ('Treeview', 'Overview.Treeview', 'Comparison.Treeview'):
        style.configure(name, font=('Segoe UI', points), rowheight=height,
                        background='white', fieldbackground='white', borderwidth=0)
        style.map(name, background=[('selected', COLORS['selection'])], foreground=[('selected', COLORS['text'])])
        style.configure(name+'.Heading', font=('Segoe UI', points, 'bold'), padding=(8, 8))
    style.configure('TProgressbar', background=COLORS['primary'], troughcolor=COLORS['background'])
    return points
