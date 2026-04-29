#!/usr/bin/env python3
"""ICC Board Controller — connect, configure, and visualize an ICC network."""

import json
import struct
import threading
import tkinter as tk
from tkinter import ttk, messagebox, colorchooser, filedialog

import serial
import serial.tools.list_ports

V_MIN = -67.6339
V_MAX = -24.1091
BAUD = 115200
INIT_HEADER = b'ICCF'
INTERVALS = ('-1', '0', '15', '20', '23', '26', '30', '40')
MAX_ROWS = 10
MAX_COLS = 10
CELL_PX = 56
LABEL_PX = 22

THEMES = {
    'Dark': {
        'bg':               '#1e1e1e',
        'fg':               '#d4d4d4',
        'fb':               '#2d2d2d',
        'disabled_fb':      '#1a1a1a',
        'border':           '#3c3c3c',
        'trough':           '#3c3c3c',
        'lf_border':        '#444444',
        'lf_label':         '#9cdcfe',
        'btn_bg':           '#3c3c3c',
        'btn_active':       '#505050',
        'canvas_bg':        '#121212',
        'cell_inactive':    '#1a1a1a',
        'cell_wait':        '#1a2e4a',
        'cell_active_mono': '#3a3a3a',
        'wait_text':        '#4a8ab5',
        'axis_label':       '#555555',
        'status_fg':        '#888888',
        'pkt_fg':           '#4ec9b0',
        'cb_list_bg':       '#2d2d2d',
        'cb_list_fg':       '#d4d4d4',
    },
    'Light': {
        'bg':               '#f3f3f3',
        'fg':               '#333333',
        'fb':               '#ffffff',
        'disabled_fb':      '#e0e0e0',
        'border':           '#cccccc',
        'trough':           '#dddddd',
        'lf_border':        '#aaaaaa',
        'lf_label':         '#0070c0',
        'btn_bg':           '#e0e0e0',
        'btn_active':       '#d0d0d0',
        'canvas_bg':        '#e8e8e8',
        'cell_inactive':    '#d0d0d0',
        'cell_wait':        '#b0cce8',
        'cell_active_mono': '#909090',
        'wait_text':        '#1060a0',
        'axis_label':       '#888888',
        'status_fg':        '#555555',
        'pkt_fg':           '#007060',
        'cb_list_bg':       '#ffffff',
        'cb_list_fg':       '#333333',
    },
}


def build_init_packet(rows, cols, step_ms, intervals, h_delays, v_delays):
    """Pack the ICCF init packet.
    h_delays: list[rows][cols-1] of ms values (ignored when cols==1)
    v_delays: list[rows-1][cols] of ms values (ignored when rows==1)
    """
    buf = bytearray(INIT_HEADER)
    buf.append(rows)
    buf.append(cols)
    buf += struct.pack('<H', step_ms)
    for r in range(rows):
        for c in range(cols):
            buf += struct.pack('<b', intervals[r][c])
    if cols > 1:
        for r in range(rows):
            for c in range(cols - 1):
                buf += struct.pack('<H', h_delays[r][c])
    if rows > 1:
        for r in range(rows - 1):
            for c in range(cols):
                buf += struct.pack('<H', v_delays[r][c])
    return bytes(buf)


def lerp_color(c1, c2, t):
    """Linearly interpolate between two '#rrggbb' hex colours."""
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    return '#{:02x}{:02x}{:02x}'.format(
        int(r1 + (r2 - r1) * t),
        int(g1 + (g2 - g1) * t),
        int(b1 + (b2 - b1) * t))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('ICC Board Controller')
        self.resizable(True, True)

        self._theme_var = tk.StringVar(value='Dark')
        self._theme = THEMES['Dark']
        self.configure(bg=self._theme['bg'])

        self._ser = None
        self._alive = False
        self._rows = 0
        self._cols = 0
        self._pkt_count = 0
        self._bytes_rx = 0
        self._iv_vars = []       # [r][c] StringVar — slow-wave intervals
        self._hpath_vars = []    # [r][c] IntVar   — H-path delays, c in [0, cols-2]
        self._vpath_vars = []    # [r][c] IntVar   — V-path delays, r in [0, rows-2]
        self._color_lo = '#ffffff'
        self._color_hi = '#0000ff'
        self._rebuild_pending = None

        self._show_values_var = tk.BooleanVar(value=True)
        self._show_colors_var = tk.BooleanVar(value=True)
        self._show_grid_var = tk.BooleanVar(value=False)
        self._show_inactive_var = tk.BooleanVar(value=True)
        self._value_color = '#000000'
        self._cell_bg_color = '#ffffff'
        self._blocked_color = '#555555'

        self._paned = ttk.PanedWindow(self, orient='horizontal')
        self._paned.pack(fill='both', expand=True)
        self._apply_style()
        self._build_left()
        self._build_right()
        self._refresh_ports()

    # ── theme ─────────────────────────────────────────────────────────────────

    def _apply_style(self):
        t = self._theme
        s = ttk.Style(self)
        s.theme_use('clam')
        bg, fg, fb = t['bg'], t['fg'], t['fb']
        s.configure('.', background=bg, foreground=fg, fieldbackground=fb,
                    bordercolor=t['border'], troughcolor=t['trough'], relief='flat')
        s.configure('TLabel', background=bg, foreground=fg)
        s.configure('TFrame', background=bg)
        s.configure('TLabelframe', background=bg, bordercolor=t['lf_border'])
        s.configure('TLabelframe.Label', background=bg, foreground=t['lf_label'])
        s.configure('TButton', background=t['btn_bg'], foreground=fg,
                    relief='flat', padding=4)
        s.map('TButton', background=[('active', t['btn_active'])])
        s.configure('Accent.TButton', background='#0e639c', foreground='white',
                    relief='flat', padding=4)
        s.map('Accent.TButton',
              background=[('active', '#1177bb'), ('disabled', '#555555')],
              foreground=[('disabled', '#aaaaaa')])
        s.configure('TCombobox', fieldbackground=fb, foreground=fg,
                    selectbackground='#0e639c', relief='flat')
        s.map('TCombobox',
              fieldbackground=[('readonly', fb), ('disabled', t['disabled_fb'])],
              foreground=[('readonly', fg), ('disabled', t['axis_label'])],
              selectforeground=[('readonly', 'white')])
        s.configure('TSpinbox', fieldbackground=fb, foreground=fg)
        s.configure('TCheckbutton', background=bg, foreground=fg)
        s.map('TCheckbutton', background=[('active', bg), ('pressed', bg)])
        self.option_add('*TCombobox*Listbox.background', t['cb_list_bg'], 80)
        self.option_add('*TCombobox*Listbox.foreground', t['cb_list_fg'], 80)
        self.option_add('*TCombobox*Listbox.selectBackground', '#0e639c', 80)
        self.option_add('*TCombobox*Listbox.selectForeground', 'white', 80)

    def _apply_theme(self, *_):
        self._theme = THEMES[self._theme_var.get()]
        self._apply_style()
        t = self._theme
        self.configure(bg=t['bg'])
        self._left_container.configure(bg=t['bg'])
        self._lcv.configure(bg=t['bg'])
        self._canvas.configure(bg=t['canvas_bg'])
        for iid in self._col_label_ids + self._row_label_ids:
            self._canvas.itemconfig(iid, fill=t['axis_label'])
        if hasattr(self, '_cells'):
            inactive_fill = t['cell_inactive'] if self._show_inactive_var.get() else t['canvas_bg']
            for rid in self._cells.values():
                self._canvas.itemconfig(rid, fill=inactive_fill, outline='')
        if hasattr(self, '_status_lbl'):
            self._status_lbl.configure(foreground=t['status_fg'])
            self._pkt_lbl.configure(foreground=t['pkt_fg'])

    # ── left panel (scrollable) ───────────────────────────────────────────────

    def _build_left(self):
        container = tk.Frame(self._paned, bg=self._theme['bg'])
        self._left_container = container
        self._paned.add(container, weight=0)

        self._lcv = tk.Canvas(container, bg=self._theme['bg'],
                               highlightthickness=0, width=420)
        vsb = ttk.Scrollbar(container, orient='vertical', command=self._lcv.yview)
        hsb = ttk.Scrollbar(container, orient='horizontal', command=self._lcv.xview)
        self._lcv.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        hsb.pack(side='bottom', fill='x')
        vsb.pack(side='right', fill='y')
        self._lcv.pack(side='left', fill='both', expand=True)

        self._left = ttk.Frame(self._lcv, padding=(8, 8, 4, 8))
        win = self._lcv.create_window((0, 0), window=self._left, anchor='nw')

        self._left.bind('<Configure>',
                        lambda e: self._lcv.configure(
                            scrollregion=self._lcv.bbox('all')))
        self._lcv.bind_all('<MouseWheel>',
                           lambda e: self._lcv.yview_scroll(
                               int(-1 * (e.delta / 120)), 'units'))
        # Prevent spinboxes and comboboxes from changing value on scroll;
        # forward to canvas scroll instead.
        for cls in ('TSpinbox', 'TCombobox'):
            self.bind_class(cls, '<MouseWheel>',
                            lambda e: self._lcv.yview_scroll(
                                int(-1 * (e.delta / 120)), 'units') or 'break')

        self._build_theme_selector(self._left)
        self._build_conn(self._left)
        self._build_icc_grid_settings(self._left)
        self.after(100, self._fit_left_panel)

    # ── theme selector ────────────────────────────────────────────────────────

    def _build_theme_selector(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill='x', pady=(0, 6))
        ttk.Label(row, text='Theme:').pack(side='left')
        ttk.Combobox(row, textvariable=self._theme_var,
                     values=list(THEMES.keys()), width=6,
                     state='readonly').pack(side='left', padx=4)
        self._theme_var.trace_add('write', self._apply_theme)

    # ── connection ────────────────────────────────────────────────────────────

    def _build_conn(self, parent):
        lf = ttk.LabelFrame(parent, text='Connection', padding=6)
        lf.pack(fill='x', pady=(0, 6))

        row = ttk.Frame(lf)
        row.pack(fill='x', pady=(0, 4))
        ttk.Label(row, text='Port').pack(side='left')
        self._port_var = tk.StringVar()
        self._port_cb = ttk.Combobox(row, textvariable=self._port_var,
                                      width=12, state='readonly')
        self._port_cb.pack(side='left', padx=4)
        ttk.Button(row, text='⟳', width=2, command=self._refresh_ports).pack(side='left')

        self._conn_btn = ttk.Button(lf, text='Connect', style='Accent.TButton',
                                     command=self._toggle_conn)
        self._conn_btn.pack(fill='x')

    # ── ICC grid settings (grouped) ───────────────────────────────────────────

    def _build_icc_grid_settings(self, parent):
        lf = ttk.LabelFrame(parent, text='ICC Grid Settings', padding=6)
        lf.pack(fill='x', pady=(0, 6))

        self._init_btn = ttk.Button(lf, text='Initialize Board',
                                     style='Accent.TButton',
                                     command=self._send_init, state='disabled')
        self._init_btn.pack(fill='x', pady=(0, 6))

        self._build_grid_config(lf)
        self._build_intervals(lf)
        self._build_hpath_section(lf)
        self._build_vpath_section(lf)

    # ── grid config ───────────────────────────────────────────────────────────

    def _build_grid_config(self, parent):
        lf = ttk.LabelFrame(parent, text='General', padding=6)
        lf.pack(fill='x', pady=(0, 6))

        r1 = ttk.Frame(lf)
        r1.pack(fill='x', pady=(0, 4))
        ttk.Label(r1, text='Rows').pack(side='left')
        self._rows_var = tk.IntVar(value=10)
        ttk.Spinbox(r1, from_=1, to=MAX_ROWS, textvariable=self._rows_var,
                    width=4).pack(side='left', padx=(3, 12))
        ttk.Label(r1, text='Cols').pack(side='left')
        self._cols_var = tk.IntVar(value=10)
        ttk.Spinbox(r1, from_=1, to=MAX_COLS, textvariable=self._cols_var,
                    width=4).pack(side='left', padx=3)

        r2 = ttk.Frame(lf)
        r2.pack(fill='x')
        ttk.Label(r2, text='Timestep (ms)').pack(side='left')
        self._step_var = tk.IntVar(value=200)
        ttk.Spinbox(r2, from_=50, to=5000, increment=50,
                    textvariable=self._step_var, width=6).pack(side='left', padx=3)
        ttk.Button(r2, text='Save', command=self._save_settings).pack(side='left', padx=(8, 2))
        ttk.Button(r2, text='Load', command=self._load_settings).pack(side='left')

        # Rebuild all grids when dimensions change.
        self._rows_var.trace_add('write', lambda *_: self._schedule_rebuild())
        self._cols_var.trace_add('write', lambda *_: self._schedule_rebuild())

    # ── slow-wave intervals ───────────────────────────────────────────────────

    def _build_intervals(self, parent):
        lf = ttk.LabelFrame(parent, text='Slow-Wave Intervals (s)', padding=6)
        lf.pack(fill='x', pady=(0, 6))

        aa = ttk.Frame(lf)
        aa.pack(fill='x', pady=(0, 4))
        ttk.Label(aa, text='All cells:').pack(side='left')
        self._iv_all_var = tk.StringVar(value='0')
        ttk.Combobox(aa, textvariable=self._iv_all_var, values=INTERVALS,
                     width=3, state='readonly').pack(side='left', padx=4)
        ttk.Button(aa, text='Apply', command=self._apply_all_intervals).pack(side='left')

        ttk.Label(lf, text='-1 = inactive, unresponsive cell',
                  foreground='#888888', font=('TkDefaultFont', 8)).pack(anchor='w', pady=(0, 4))

        self._iv_frame = ttk.Frame(lf)
        self._iv_frame.pack(fill='x')
        self._rebuild_ivgrid()

    def _rebuild_ivgrid(self):
        for w in self._iv_frame.winfo_children():
            w.destroy()
        try:
            rows = max(1, min(MAX_ROWS, int(self._rows_var.get())))
            cols = max(1, min(MAX_COLS, int(self._cols_var.get())))
        except (tk.TclError, ValueError):
            return
        old = self._iv_vars
        self._iv_vars = []
        for r in range(rows):
            row_vars = []
            rf = ttk.Frame(self._iv_frame)
            rf.pack(anchor='w')
            for c in range(cols):
                prev = old[r][c].get() if r < len(old) and c < len(old[r]) else self._iv_all_var.get()
                v = tk.StringVar(value=prev)
                ttk.Combobox(rf, textvariable=v, values=INTERVALS,
                             width=3, state='readonly').pack(side='left', padx=1, pady=1)
                row_vars.append(v)
            self._iv_vars.append(row_vars)

    def _apply_all_intervals(self):
        val = self._iv_all_var.get()
        for row in self._iv_vars:
            for v in row:
                v.set(val)

    # ── H-path delays ─────────────────────────────────────────────────────────

    def _build_hpath_section(self, parent):
        lf = ttk.LabelFrame(parent, text='H-Path Delays (ms)', padding=6)
        lf.pack(fill='x', pady=(0, 6))

        aa = ttk.Frame(lf)
        aa.pack(fill='x', pady=(0, 4))
        ttk.Label(aa, text='All H-paths:').pack(side='left')
        self._hd_all_var = tk.IntVar(value=1000)
        ttk.Spinbox(aa, from_=0, to=60000, increment=100,
                    textvariable=self._hd_all_var, width=6).pack(side='left', padx=4)
        ttk.Button(aa, text='Apply', command=self._apply_all_hdelays).pack(side='left')

        self._hpath_frame = ttk.Frame(lf)
        self._hpath_frame.pack(fill='x')
        self._rebuild_hpath_grid()

    def _rebuild_hpath_grid(self):
        for w in self._hpath_frame.winfo_children():
            w.destroy()
        try:
            rows = max(1, min(MAX_ROWS, int(self._rows_var.get())))
            cols = max(1, min(MAX_COLS, int(self._cols_var.get())))
        except (tk.TclError, ValueError):
            return

        if cols < 2:
            ttk.Label(self._hpath_frame,
                      text='(no H-paths with 1 column)', foreground='#555').pack(anchor='w')
            self._hpath_vars = []
            return

        old = self._hpath_vars
        self._hpath_vars = []
        for r in range(rows):
            row_vars = []
            rf = ttk.Frame(self._hpath_frame)
            rf.pack(anchor='w')
            ttk.Label(rf, text=f'r{r}:', width=3).pack(side='left')
            for c in range(cols - 1):
                prev = old[r][c].get() if r < len(old) and c < len(old[r]) else self._hd_all_var.get()
                v = tk.IntVar(value=prev)
                ttk.Spinbox(rf, from_=0, to=60000, increment=100,
                            textvariable=v, width=5).pack(side='left', padx=1, pady=1)
                row_vars.append(v)
            self._hpath_vars.append(row_vars)

    def _apply_all_hdelays(self):
        val = self._hd_all_var.get()
        for row in self._hpath_vars:
            for v in row:
                v.set(val)

    # ── V-path delays ─────────────────────────────────────────────────────────

    def _build_vpath_section(self, parent):
        lf = ttk.LabelFrame(parent, text='V-Path Delays (ms)', padding=6)
        lf.pack(fill='x', pady=(0, 6))

        aa = ttk.Frame(lf)
        aa.pack(fill='x', pady=(0, 4))
        ttk.Label(aa, text='All V-paths:').pack(side='left')
        self._vd_all_var = tk.IntVar(value=1000)
        ttk.Spinbox(aa, from_=0, to=60000, increment=100,
                    textvariable=self._vd_all_var, width=6).pack(side='left', padx=4)
        ttk.Button(aa, text='Apply', command=self._apply_all_vdelays).pack(side='left')

        self._vpath_frame = ttk.Frame(lf)
        self._vpath_frame.pack(fill='x')
        self._rebuild_vpath_grid()

    def _rebuild_vpath_grid(self):
        for w in self._vpath_frame.winfo_children():
            w.destroy()
        try:
            rows = max(1, min(MAX_ROWS, int(self._rows_var.get())))
            cols = max(1, min(MAX_COLS, int(self._cols_var.get())))
        except (tk.TclError, ValueError):
            return

        if rows < 2:
            ttk.Label(self._vpath_frame,
                      text='(no V-paths with 1 row)', foreground='#555').pack(anchor='w')
            self._vpath_vars = []
            return

        old = self._vpath_vars
        self._vpath_vars = []
        for r in range(rows - 1):
            row_vars = []
            rf = ttk.Frame(self._vpath_frame)
            rf.pack(anchor='w')
            ttk.Label(rf, text=f'r{r}↓:', width=4).pack(side='left')
            for c in range(cols):
                prev = old[r][c].get() if r < len(old) and c < len(old[r]) else self._vd_all_var.get()
                v = tk.IntVar(value=prev)
                ttk.Spinbox(rf, from_=0, to=60000, increment=100,
                            textvariable=v, width=5).pack(side='left', padx=1, pady=1)
                row_vars.append(v)
            self._vpath_vars.append(row_vars)

    def _apply_all_vdelays(self):
        val = self._vd_all_var.get()
        for row in self._vpath_vars:
            for v in row:
                v.set(val)

    # ── display config ────────────────────────────────────────────────────────

    def _build_display(self, parent):
        lf = ttk.LabelFrame(parent, text='Live Viewer Settings', padding=6)
        lf.pack(fill='x', pady=(6, 0))

        # All toggles on one row
        tr = ttk.Frame(lf)
        tr.pack(fill='x', pady=(0, 6))
        ttk.Checkbutton(tr, text='Show values',
                        variable=self._show_values_var).pack(side='left', padx=(0, 12))
        ttk.Checkbutton(tr, text='Show colors',
                        variable=self._show_colors_var).pack(side='left', padx=(0, 12))
        ttk.Checkbutton(tr, text='Show grid',
                        variable=self._show_grid_var).pack(side='left', padx=(0, 12))
        ttk.Checkbutton(tr, text='Show inactive cells',
                        variable=self._show_inactive_var).pack(side='left')

        vr = ttk.Frame(lf)
        vr.pack(fill='x', pady=(0, 8))
        ttk.Label(vr, text='V min').pack(side='left')
        self._v_min_var = tk.DoubleVar(value=V_MIN)
        ttk.Spinbox(vr, from_=-200.0, to=0.0, increment=0.5, format='%.1f',
                    textvariable=self._v_min_var, width=7).pack(side='left', padx=(3, 12))
        ttk.Label(vr, text='V max').pack(side='left')
        self._v_max_var = tk.DoubleVar(value=V_MAX)
        ttk.Spinbox(vr, from_=-200.0, to=0.0, increment=0.5, format='%.1f',
                    textvariable=self._v_max_var, width=7).pack(side='left', padx=3)

        # Color pickers: 2-column grid
        cg = ttk.Frame(lf)
        cg.pack(fill='x')

        def _color_row(parent_grid, row, col, swatch_attr, color_val, label, cmd, padx_right=16):
            f = ttk.Frame(parent_grid)
            f.grid(row=row, column=col, sticky='w',
                   padx=(0, padx_right if col == 0 else 0), pady=(0, 6))
            sw = tk.Label(f, bg=color_val, width=3, relief='solid')
            sw.pack(side='left', padx=(0, 4))
            setattr(self, swatch_attr, sw)
            ttk.Button(f, text=label, command=cmd).pack(side='left')

        _color_row(cg, 0, 0, '_lo_swatch',          self._color_lo,      'Low color',        self._pick_lo_color)
        _color_row(cg, 0, 1, '_hi_swatch',          self._color_hi,      'High color',       self._pick_hi_color)
        _color_row(cg, 1, 0, '_value_color_swatch', self._value_color,   'Value text color', self._pick_value_color)
        _color_row(cg, 1, 1, '_cell_bg_swatch',     self._cell_bg_color, 'Background color', self._pick_cell_bg_color)
        _color_row(cg, 2, 0, '_blocked_swatch',     self._blocked_color, 'Blocked cell color', self._pick_blocked_color, padx_right=0)

    def _pick_value_color(self):
        result = colorchooser.askcolor(color=self._value_color, title='Value text colour')
        if result[1]:
            self._value_color = result[1]
            self._value_color_swatch.configure(bg=self._value_color)

    def _pick_cell_bg_color(self):
        result = colorchooser.askcolor(color=self._cell_bg_color, title='Cell background colour')
        if result[1]:
            self._cell_bg_color = result[1]
            self._cell_bg_swatch.configure(bg=self._cell_bg_color)

    def _pick_blocked_color(self):
        result = colorchooser.askcolor(color=self._blocked_color, title='Blocked cell colour')
        if result[1]:
            self._blocked_color = result[1]
            self._blocked_swatch.configure(bg=self._blocked_color)

    def _pick_lo_color(self):
        result = colorchooser.askcolor(color=self._color_lo, title='Low voltage colour')
        if result[1]:
            self._color_lo = result[1]
            self._lo_swatch.configure(bg=self._color_lo)

    def _pick_hi_color(self):
        result = colorchooser.askcolor(color=self._color_hi, title='High voltage colour')
        if result[1]:
            self._color_hi = result[1]
            self._hi_swatch.configure(bg=self._color_hi)

    # ── rebuild all grids on dimension change ─────────────────────────────────

    def _schedule_rebuild(self):
        if self._rebuild_pending is not None:
            self.after_cancel(self._rebuild_pending)
        self._rebuild_pending = self.after(150, self._do_rebuild)

    def _do_rebuild(self):
        self._rebuild_pending = None
        self._rebuild_all()
        try:
            rows = max(1, min(MAX_ROWS, int(self._rows_var.get())))
            cols = max(1, min(MAX_COLS, int(self._cols_var.get())))
            if hasattr(self, '_canvas'):
                self._resize_canvas(rows, cols)
        except (tk.TclError, ValueError):
            pass

    def _rebuild_all(self):
        if hasattr(self, '_iv_frame'):
            self._rebuild_ivgrid()
        if hasattr(self, '_hpath_frame'):
            self._rebuild_hpath_grid()
        if hasattr(self, '_vpath_frame'):
            self._rebuild_vpath_grid()

    def _resize_canvas(self, rows, cols):
        cw = LABEL_PX + cols * CELL_PX
        ch = LABEL_PX + rows * CELL_PX
        self._canvas.configure(width=cw, height=ch)
        for c, iid in enumerate(self._col_label_ids):
            self._canvas.itemconfig(iid, state='normal' if c < cols else 'hidden')
        for r, iid in enumerate(self._row_label_ids):
            self._canvas.itemconfig(iid, state='normal' if r < rows else 'hidden')
        self.after(50, self._fit_window)

    def _fit_left_panel(self):
        self.update_idletasks()
        w = self._left.winfo_reqwidth() + 16  # +16 for vertical scrollbar
        self._lcv.configure(width=w)
        self._paned.sashpos(0, w)
        self.after(50, self._fit_window)

    def _fit_window(self):
        self.update_idletasks()
        lw = self._lcv.winfo_width()
        rw = self._right_frame.winfo_reqwidth()
        self.geometry(f'{lw + rw}x{self.winfo_reqheight()}')

    # ── right panel (heatmap) ─────────────────────────────────────────────────

    def _build_right(self):
        right = ttk.Frame(self._paned, padding=(4, 8, 8, 8))
        self._paned.add(right, weight=1)
        self._right_frame = right

        lf = ttk.LabelFrame(right, text='Live ICC Activity Viewer', padding=6)
        lf.pack(fill='both', expand=True)

        cw = LABEL_PX + MAX_COLS * CELL_PX
        ch = LABEL_PX + MAX_ROWS * CELL_PX
        self._canvas = tk.Canvas(lf, bg=self._theme['canvas_bg'], highlightthickness=0,
                                  width=cw, height=ch)
        self._canvas.pack(fill='x')
        self._build_display(lf)

        self._cells = {}
        self._ctexts = {}
        self._col_label_ids = []
        self._row_label_ids = []

        for c in range(MAX_COLS):
            x = LABEL_PX + c * CELL_PX + CELL_PX // 2
            iid = self._canvas.create_text(x, LABEL_PX // 2, text=str(c),
                                            fill=self._theme['axis_label'],
                                            font=('Consolas', 8))
            self._col_label_ids.append(iid)
        for r in range(MAX_ROWS):
            y = LABEL_PX + r * CELL_PX + CELL_PX // 2
            iid = self._canvas.create_text(LABEL_PX // 2, y, text=str(r),
                                            fill=self._theme['axis_label'],
                                            font=('Consolas', 8))
            self._row_label_ids.append(iid)

        for r in range(MAX_ROWS):
            for c in range(MAX_COLS):
                x0 = LABEL_PX + c * CELL_PX
                y0 = LABEL_PX + r * CELL_PX
                rid = self._canvas.create_rectangle(
                    x0, y0, x0 + CELL_PX, y0 + CELL_PX,
                    fill=self._theme['cell_inactive'], outline='')
                tid = self._canvas.create_text(
                    x0 + CELL_PX // 2, y0 + CELL_PX // 2,
                    text='', fill=self._theme['axis_label'], font=('Consolas', 8))
                self._cells[(r, c)] = rid
                self._ctexts[(r, c)] = tid

        bar = ttk.Frame(right)
        bar.pack(fill='x', pady=(4, 0))
        self._status_var = tk.StringVar(value='Disconnected')
        self._status_lbl = ttk.Label(bar, textvariable=self._status_var,
                                      foreground=self._theme['status_fg'])
        self._status_lbl.pack(side='left')
        self._pkt_var = tk.StringVar(value='')
        self._pkt_lbl = ttk.Label(bar, textvariable=self._pkt_var,
                                   foreground=self._theme['pkt_fg'])
        self._pkt_lbl.pack(side='right')

    # ── voltage → colour ──────────────────────────────────────────────────────

    def _v_to_color(self, v):
        if v == 0.0:
            return self._theme['cell_wait']
        try:
            v_min = float(self._v_min_var.get())
            v_max = float(self._v_max_var.get())
        except (tk.TclError, ValueError):
            v_min, v_max = V_MIN, V_MAX
        if v_max == v_min:
            t = 0.5
        else:
            t = max(0.0, min(1.0, (v - v_min) / (v_max - v_min)))
        return lerp_color(self._color_lo, self._color_hi, t)

    # ── serial ────────────────────────────────────────────────────────────────

    def _refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self._port_cb['values'] = ports
        if ports and not self._port_var.get():
            self._port_var.set(ports[0])

    def _toggle_conn(self):
        if self._ser and self._ser.is_open:
            self._do_disconnect()
        else:
            self._do_connect()

    def _do_connect(self):
        port = self._port_var.get()
        if not port:
            messagebox.showerror('Error', 'Select a serial port.')
            return
        try:
            self._ser = serial.Serial(port, BAUD, timeout=0.1)
        except serial.SerialException as exc:
            messagebox.showerror('Connection failed', str(exc))
            return
        self._ser.setDTR(False)
        self.after(100, self._release_dtr)
        self._bytes_rx = 0
        self._alive = True
        self._conn_btn.config(text='Disconnect')
        self._status_var.set(f'Connected  {port}  —  resetting board…')
        threading.Thread(target=self._read_loop, daemon=True).start()
        self.after(2500, self._on_board_ready)

    def _release_dtr(self):
        if self._ser and self._ser.is_open:
            try:
                self._ser.setDTR(True)
            except Exception:
                pass

    def _on_board_ready(self):
        if self._ser and self._ser.is_open:
            self._init_btn.config(state='normal')
            self._status_var.set('Ready  —  click Initialize Board to start')

    def _do_disconnect(self):
        self._alive = False
        if self._ser:
            self._ser.close()
            self._ser = None
        self._conn_btn.config(text='Connect')
        self._init_btn.config(state='disabled')
        self._status_var.set('Disconnected')
        self._pkt_var.set('')
        self._rows = 0
        self._cols = 0
        self._bytes_rx = 0

    def _send_init(self):
        if not (self._ser and self._ser.is_open):
            return
        # Flush any deferred grid rebuild so dimension spinboxes and _iv_vars are in sync.
        if self._rebuild_pending is not None:
            self.after_cancel(self._rebuild_pending)
            self._rebuild_pending = None
            self._rebuild_all()
        try:
            rows = max(1, min(MAX_ROWS, int(self._rows_var.get())))
            cols = max(1, min(MAX_COLS, int(self._cols_var.get())))
            step = int(self._step_var.get())
        except (tk.TclError, ValueError) as exc:
            messagebox.showerror('Invalid input', str(exc))
            return

        intervals = [[int(self._iv_vars[r][c].get()) for c in range(cols)]
                     for r in range(rows)]

        h_delays = ([[self._hpath_vars[r][c].get() for c in range(cols - 1)]
                     for r in range(rows)]
                    if cols > 1 and self._hpath_vars else [])

        v_delays = ([[self._vpath_vars[r][c].get() for c in range(cols)]
                     for r in range(rows - 1)]
                    if rows > 1 and self._vpath_vars else [])

        packet = build_init_packet(rows, cols, step, intervals, h_delays, v_delays)

        self._rows = rows
        self._cols = cols
        self._pkt_count = 0
        self._resize_canvas(rows, cols)
        self._ser.reset_input_buffer()
        self._ser.write(packet)
        self._status_var.set(f'Running  {rows}×{cols}  step={step} ms')

    # ── background serial reader ──────────────────────────────────────────────

    def _read_loop(self):
        buf = bytearray()
        while self._alive:
            try:
                chunk = self._ser.read(256)
            except Exception as exc:
                self.after(0, self._status_var.set, f'Serial error: {exc}')
                break
            if not chunk:
                continue
            buf += chunk
            self._bytes_rx += len(chunk)
            self.after(0, self._pkt_var.set,
                       f'rx {self._bytes_rx} B   pkts {self._pkt_count}')

            while len(buf) >= 2:
                idx = next(
                    (i for i in range(len(buf) - 1)
                     if buf[i] == 0xAA and buf[i + 1] == 0x55),
                    -1)
                if idx == -1:
                    buf = buf[-1:]
                    break
                buf = buf[idx:]

                rows, cols = self._rows, self._cols
                if rows == 0 or cols == 0:
                    buf = buf[2:]
                    break

                pkt_len = 2 + rows * cols * 4
                if len(buf) < pkt_len:
                    break

                payload = bytes(buf[2:pkt_len])
                buf = buf[pkt_len:]
                voltages = struct.unpack(f'<{rows * cols}f', payload)
                self._pkt_count += 1
                self.after(0, self._on_voltages, rows, cols, voltages)

    def _on_voltages(self, rows, cols, voltages):
        show_v = self._show_values_var.get()
        show_c = self._show_colors_var.get()
        show_inactive = self._show_inactive_var.get()
        grid_outline = '#444444' if self._show_grid_var.get() else ''
        t = self._theme
        for r in range(MAX_ROWS):
            for c in range(MAX_COLS):
                rid = self._cells[(r, c)]
                tid = self._ctexts[(r, c)]
                if r < rows and c < cols:
                    is_blocked = (r < len(self._iv_vars) and
                                  c < len(self._iv_vars[r]) and
                                  self._iv_vars[r][c].get() == '-1')
                    if is_blocked:
                        fill = t['canvas_bg'] if not show_inactive else self._blocked_color
                        self._canvas.itemconfig(rid, fill=fill, outline='')
                        self._canvas.itemconfig(tid, text='')
                    else:
                        v = voltages[r * cols + c]
                        is_wait = (v == 0.0)
                        fill = self._v_to_color(v) if show_c else self._cell_bg_color
                        self._canvas.itemconfig(rid, fill=fill, outline=grid_outline)
                        self._canvas.itemconfig(
                            tid,
                            text=('WAIT' if is_wait else f'{v:.1f}') if show_v else '',
                            fill=t['wait_text'] if is_wait else self._value_color)
                else:
                    inactive_fill = t['cell_inactive'] if show_inactive else t['canvas_bg']
                    self._canvas.itemconfig(rid, fill=inactive_fill, outline='')
                    self._canvas.itemconfig(tid, text='')

    # ── save / load settings ──────────────────────────────────────────────────

    def _save_settings(self):
        path = filedialog.asksaveasfilename(
            defaultextension='.json',
            filetypes=[('JSON files', '*.json'), ('All files', '*.*')],
            title='Save ICC Grid Settings')
        if not path:
            return
        try:
            rows = max(1, min(MAX_ROWS, int(self._rows_var.get())))
            cols = max(1, min(MAX_COLS, int(self._cols_var.get())))
            step = int(self._step_var.get())
        except (tk.TclError, ValueError) as exc:
            messagebox.showerror('Invalid input', str(exc))
            return
        intervals = [[int(self._iv_vars[r][c].get()) for c in range(cols)]
                     for r in range(rows)]
        h_delays = ([[self._hpath_vars[r][c].get() for c in range(cols - 1)]
                     for r in range(rows)]
                    if cols > 1 and self._hpath_vars else [])
        v_delays = ([[self._vpath_vars[r][c].get() for c in range(cols)]
                     for r in range(rows - 1)]
                    if rows > 1 and self._vpath_vars else [])
        data = {
            'rows': rows,
            'cols': cols,
            'step_ms': step,
            'intervals': intervals,
            'h_delays': h_delays,
            'v_delays': v_delays,
        }
        try:
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        except OSError as exc:
            messagebox.showerror('Save failed', str(exc))

    def _load_settings(self):
        path = filedialog.askopenfilename(
            filetypes=[('JSON files', '*.json'), ('All files', '*.*')],
            title='Load ICC Grid Settings')
        if not path:
            return
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror('Load failed', str(exc))
            return
        try:
            rows = max(1, min(MAX_ROWS, int(data['rows'])))
            cols = max(1, min(MAX_COLS, int(data['cols'])))
            step = int(data['step_ms'])
        except (KeyError, ValueError) as exc:
            messagebox.showerror('Invalid file', str(exc))
            return

        self._rows_var.set(rows)
        self._cols_var.set(cols)
        self._step_var.set(step)

        if self._rebuild_pending is not None:
            self.after_cancel(self._rebuild_pending)
            self._rebuild_pending = None
        self._rebuild_all()
        self._resize_canvas(rows, cols)

        for r, row_vals in enumerate(data.get('intervals', [])):
            for c, val in enumerate(row_vals):
                if r < len(self._iv_vars) and c < len(self._iv_vars[r]):
                    self._iv_vars[r][c].set(str(val))

        for r, row_vals in enumerate(data.get('h_delays', [])):
            for c, val in enumerate(row_vals):
                if self._hpath_vars and r < len(self._hpath_vars) and c < len(self._hpath_vars[r]):
                    self._hpath_vars[r][c].set(int(val))

        for r, row_vals in enumerate(data.get('v_delays', [])):
            for c, val in enumerate(row_vals):
                if self._vpath_vars and r < len(self._vpath_vars) and c < len(self._vpath_vars[r]):
                    self._vpath_vars[r][c].set(int(val))

    def on_close(self):
        self._do_disconnect()
        self.destroy()


if __name__ == '__main__':
    app = App()
    app.protocol('WM_DELETE_WINDOW', app.on_close)
    app.mainloop()
