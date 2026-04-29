#!/usr/bin/env python3
"""ICC Board Controller — connect, configure, and visualize an ICC network."""

import struct
import threading
import tkinter as tk
from tkinter import ttk, messagebox, colorchooser

import serial
import serial.tools.list_ports

V_MIN = -67.6339
V_MAX = -24.1091
BAUD = 115200
INIT_HEADER = b'ICCF'
INTERVALS = ('0', '20', '23', '30', '40')
MAX_ROWS = 10
MAX_COLS = 10
CELL_PX = 56
LABEL_PX = 22


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
            buf.append(intervals[r][c])
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
        self.configure(bg='#1e1e1e')
        self.resizable(True, True)

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

        self._apply_style()
        self._build_left()
        self._build_right()
        self._refresh_ports()

    # ── theme ─────────────────────────────────────────────────────────────────

    def _apply_style(self):
        s = ttk.Style(self)
        s.theme_use('clam')
        bg, fg, fb = '#1e1e1e', '#d4d4d4', '#2d2d2d'
        s.configure('.', background=bg, foreground=fg, fieldbackground=fb,
                    bordercolor='#3c3c3c', troughcolor='#3c3c3c', relief='flat')
        s.configure('TLabel', background=bg, foreground=fg)
        s.configure('TFrame', background=bg)
        s.configure('TLabelframe', background=bg, bordercolor='#444')
        s.configure('TLabelframe.Label', background=bg, foreground='#9cdcfe')
        s.configure('TButton', background='#3c3c3c', foreground=fg,
                    relief='flat', padding=4)
        s.map('TButton', background=[('active', '#505050')])
        s.configure('Accent.TButton', background='#0e639c', foreground='white',
                    relief='flat', padding=4)
        s.map('Accent.TButton',
              background=[('active', '#1177bb'), ('disabled', '#2a2a2a')],
              foreground=[('disabled', '#555')])
        s.configure('TCombobox', fieldbackground=fb, foreground=fg,
                    selectbackground='#0e639c', relief='flat')
        s.map('TCombobox',
              fieldbackground=[('readonly', fb), ('disabled', '#1a1a1a')],
              foreground=[('readonly', fg), ('disabled', '#555')],
              selectforeground=[('readonly', 'white')])
        s.configure('TSpinbox', fieldbackground=fb, foreground=fg)
        self.option_add('*TCombobox*Listbox.background', '#2d2d2d')
        self.option_add('*TCombobox*Listbox.foreground', '#d4d4d4')
        self.option_add('*TCombobox*Listbox.selectBackground', '#0e639c')
        self.option_add('*TCombobox*Listbox.selectForeground', 'white')

    # ── left panel (scrollable) ───────────────────────────────────────────────

    def _build_left(self):
        container = tk.Frame(self, bg='#1e1e1e')
        container.grid(row=0, column=0, sticky='nsew')
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=0)

        self._lcv = tk.Canvas(container, bg='#1e1e1e',
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

        self._build_conn(self._left)
        self._init_btn = ttk.Button(self._left, text='Initialize Board',
                                     style='Accent.TButton',
                                     command=self._send_init, state='disabled')
        self._init_btn.pack(fill='x', pady=(0, 6))
        self._build_grid_config(self._left)
        self._build_intervals(self._left)
        self._build_hpath_section(self._left)
        self._build_vpath_section(self._left)
        self._build_display(self._left)

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

    # ── grid config ───────────────────────────────────────────────────────────

    def _build_grid_config(self, parent):
        lf = ttk.LabelFrame(parent, text='Grid', padding=6)
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
        self._iv_all_var = tk.StringVar(value='20')
        ttk.Combobox(aa, textvariable=self._iv_all_var, values=INTERVALS,
                     width=3, state='readonly').pack(side='left', padx=4)
        ttk.Button(aa, text='Apply', command=self._apply_all_intervals).pack(side='left')

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
        self._hd_all_var = tk.IntVar(value=2000)
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
        self._vd_all_var = tk.IntVar(value=2000)
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
        lf = ttk.LabelFrame(parent, text='Display', padding=6)
        lf.pack(fill='x', pady=(0, 6))

        vr = ttk.Frame(lf)
        vr.pack(fill='x', pady=(0, 6))
        ttk.Label(vr, text='V min').pack(side='left')
        self._v_min_var = tk.DoubleVar(value=V_MIN)
        ttk.Spinbox(vr, from_=-200.0, to=0.0, increment=0.5, format='%.1f',
                    textvariable=self._v_min_var, width=7).pack(side='left', padx=(3, 12))
        ttk.Label(vr, text='V max').pack(side='left')
        self._v_max_var = tk.DoubleVar(value=V_MAX)
        ttk.Spinbox(vr, from_=-200.0, to=0.0, increment=0.5, format='%.1f',
                    textvariable=self._v_max_var, width=7).pack(side='left', padx=3)

        cr = ttk.Frame(lf)
        cr.pack(fill='x')
        self._lo_swatch = tk.Label(cr, bg=self._color_lo, width=3, relief='solid')
        self._lo_swatch.pack(side='left', padx=(0, 4))
        ttk.Button(cr, text='Low color',
                   command=self._pick_lo_color).pack(side='left', padx=(0, 12))
        self._hi_swatch = tk.Label(cr, bg=self._color_hi, width=3, relief='solid')
        self._hi_swatch.pack(side='left', padx=(0, 4))
        ttk.Button(cr, text='High color',
                   command=self._pick_hi_color).pack(side='left')

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

    def _rebuild_all(self):
        if hasattr(self, '_iv_frame'):
            self._rebuild_ivgrid()
        if hasattr(self, '_hpath_frame'):
            self._rebuild_hpath_grid()
        if hasattr(self, '_vpath_frame'):
            self._rebuild_vpath_grid()

    # ── right panel (heatmap) ─────────────────────────────────────────────────

    def _build_right(self):
        right = ttk.Frame(self, padding=(4, 8, 8, 8))
        right.grid(row=0, column=1, sticky='nsew')
        self.grid_columnconfigure(1, weight=1)

        lf = ttk.LabelFrame(right, text='Live Voltages', padding=6)
        lf.pack(fill='both', expand=True)

        cw = LABEL_PX + MAX_COLS * CELL_PX
        ch = LABEL_PX + MAX_ROWS * CELL_PX
        self._canvas = tk.Canvas(lf, bg='#121212', highlightthickness=0,
                                  width=cw, height=ch)
        self._canvas.pack()

        self._cells = {}
        self._ctexts = {}

        for c in range(MAX_COLS):
            x = LABEL_PX + c * CELL_PX + CELL_PX // 2
            self._canvas.create_text(x, LABEL_PX // 2, text=str(c),
                                      fill='#555', font=('Consolas', 8))
        for r in range(MAX_ROWS):
            y = LABEL_PX + r * CELL_PX + CELL_PX // 2
            self._canvas.create_text(LABEL_PX // 2, y, text=str(r),
                                      fill='#555', font=('Consolas', 8))

        for r in range(MAX_ROWS):
            for c in range(MAX_COLS):
                x0 = LABEL_PX + c * CELL_PX
                y0 = LABEL_PX + r * CELL_PX
                rid = self._canvas.create_rectangle(
                    x0, y0, x0 + CELL_PX, y0 + CELL_PX,
                    fill='#1a1a1a', outline='#2a2a2a')
                tid = self._canvas.create_text(
                    x0 + CELL_PX // 2, y0 + CELL_PX // 2,
                    text='', fill='#444', font=('Consolas', 8))
                self._cells[(r, c)] = rid
                self._ctexts[(r, c)] = tid

        bar = ttk.Frame(right)
        bar.pack(fill='x', pady=(4, 0))
        self._status_var = tk.StringVar(value='Disconnected')
        ttk.Label(bar, textvariable=self._status_var, foreground='#888').pack(side='left')
        self._pkt_var = tk.StringVar(value='')
        ttk.Label(bar, textvariable=self._pkt_var, foreground='#4ec9b0').pack(side='right')

    # ── voltage → colour ──────────────────────────────────────────────────────

    def _v_to_color(self, v):
        if v == 0.0:
            return '#1a2e4a'   # WAIT state — distinct from inactive cells
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
        for r in range(MAX_ROWS):
            for c in range(MAX_COLS):
                rid = self._cells[(r, c)]
                tid = self._ctexts[(r, c)]
                if r < rows and c < cols:
                    v = voltages[r * cols + c]
                    is_wait = (v == 0.0)
                    self._canvas.itemconfig(rid, fill=self._v_to_color(v))
                    self._canvas.itemconfig(
                        tid,
                        text='WAIT' if is_wait else f'{v:.1f}',
                        fill='#4a8ab5' if is_wait else 'white')
                else:
                    self._canvas.itemconfig(rid, fill='#1a1a1a')
                    self._canvas.itemconfig(tid, text='')

    def on_close(self):
        self._do_disconnect()
        self.destroy()


if __name__ == '__main__':
    app = App()
    app.protocol('WM_DELETE_WINDOW', app.on_close)
    app.mainloop()
