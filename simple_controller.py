from __future__ import annotations

import struct
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import colorchooser, messagebox, ttk

import serial
from serial.tools import list_ports


HEADER = b"ICCF"
TELEMETRY_HEADER = b"\xAA\x55"
BAUD = 115200
MAX_ROWS = 10
MAX_COLS = 10
MAX_TOTAL_CELLS = 25
UINT16_MAX = 65535
SUPPORTED_FREQS = (20, 23, 30, 40)


@dataclass
class Settings:
    rows: int = 1
    cols: int = 10
    time_step_ms: int = 200
    icc_freq: int = 20
    path_delay_ms: int = 2000
    v_min: float = -67.0
    v_max: float = -24.1
    low_color: str = "#ffffff"
    high_color: str = "#2563eb"


class SerialReader(threading.Thread):
    def __init__(self, port: str, settings: Settings, on_frame, on_status, on_error, icc_vars=None, path_vars=None):
        super().__init__(daemon=True)
        self.port = port
        self.settings = settings
        self.on_frame = on_frame
        self.on_status = on_status
        self.on_error = on_error
        self.stop_flag = threading.Event()
        self.serial_port: serial.Serial | None = None
        # references to UI variable matrices (populated by App)
        self.icc_vars = icc_vars
        self.path_vars = path_vars

    def stop(self):
        self.stop_flag.set()
        if self.serial_port is not None:
            try:
                self.serial_port.close()
            except Exception:
                pass

    def run(self):
        try:
            self.serial_port = serial.Serial(self.port, BAUD, timeout=0.05)
            self.serial_port.reset_input_buffer()
            self.serial_port.write(self._config_packet())
            self.serial_port.flush()
            self.on_status(f"Connected to {self.port}")
        except Exception as exc:
            self.on_error(f"Could not open {self.port}: {exc}")
            return

        rows = max(1, min(MAX_ROWS, int(self.settings.rows)))
        cols = max(1, min(MAX_COLS, int(self.settings.cols)))
        expected_floats = rows * cols
        expected_frame = 2 + (expected_floats * 4)
        buffer = bytearray()

        try:
            while not self.stop_flag.is_set():
                assert self.serial_port is not None
                chunk = self.serial_port.read(max(1, self.serial_port.in_waiting or 1))
                if chunk:
                    buffer.extend(chunk)

                while True:
                    start = buffer.find(TELEMETRY_HEADER)
                    if start < 0:
                        if len(buffer) > 1:
                            del buffer[:-1]
                        break
                    if start > 0:
                        del buffer[:start]
                    if len(buffer) < expected_frame:
                        break

                    payload = bytes(buffer[2:expected_frame])
                    del buffer[:expected_frame]
                    try:
                        values = struct.unpack("<" + ("f" * expected_floats), payload)
                    except struct.error:
                        continue
                    self.on_frame(list(values))

        except Exception as exc:
            self.on_error(f"Serial stream error: {exc}")
        finally:
            if self.serial_port is not None:
                try:
                    self.serial_port.close()
                except Exception:
                    pass

    def _config_packet(self) -> bytes:
        rows = max(1, min(MAX_ROWS, int(self.settings.rows)))
        cols = max(1, min(MAX_COLS, int(self.settings.cols)))
        if rows * cols > MAX_TOTAL_CELLS:
            raise ValueError("Grid is too large for the Uno build (max 25 cells).")

        packet = bytearray()
        packet.extend(HEADER)
        packet.extend(struct.pack(
            "<BBH",
            rows,
            cols,
            int(self.settings.time_step_ms),
        ))

        for r in range(rows):
            for c in range(cols):
                freq = clamp_int(self.icc_vars[r][c].get(), min(SUPPORTED_FREQS), max(SUPPORTED_FREQS))
                packet.extend(struct.pack("<B", freq))

        h_cols = max(cols - 1, 0)
        if h_cols > 0:
            for r in range(rows):
                for c in range(h_cols):
                    delay_ms = clamp_int(self.path_vars[r][c].get(), 0, UINT16_MAX)
                    packet.extend(struct.pack("<H", delay_ms))

        v_rows = max(rows - 1, 0)
        if v_rows > 0:
            offset = rows if h_cols > 0 else 0
            for r in range(v_rows):
                for c in range(cols):
                    delay_ms = clamp_int(self.path_vars[offset + r][c].get(), 0, UINT16_MAX)
                    packet.extend(struct.pack("<H", delay_ms))

        return bytes(packet)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ICC Controller")
        self.geometry("1500x860")
        self.minsize(1200, 760)

        self.settings = Settings()
        self.reader: SerialReader | None = None
        self.connected = False

        self.port_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Disconnected")
        self.rows_var = tk.IntVar(value=self.settings.rows)
        self.cols_var = tk.IntVar(value=self.settings.cols)
        self.time_step_var = tk.IntVar(value=self.settings.time_step_ms)
        self.icc_freq_all_var = tk.IntVar(value=self.settings.icc_freq)
        self.path_delay_all_var = tk.IntVar(value=self.settings.path_delay_ms)
        self.v_min_var = tk.DoubleVar(value=self.settings.v_min)
        self.v_max_var = tk.DoubleVar(value=self.settings.v_max)
        self.low_color_var = tk.StringVar(value=self.settings.low_color)
        self.high_color_var = tk.StringVar(value=self.settings.high_color)

        self.icc_vars: list[list[tk.StringVar]] = []
        self.path_vars: list[list[tk.StringVar]] = []
        self.values: list[float] = [self.settings.v_min] * (self.settings.rows * self.settings.cols)

        self._build_ui()
        self._refresh_ports()
        self._rebuild_grids()
        self.after(40, self._tick)

    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background="#111827")
        style.configure("TLabel", background="#111827", foreground="#e5e7eb", font=("Segoe UI", 10))
        style.configure("Title.TLabel", background="#111827", foreground="#ffffff", font=("Segoe UI Semibold", 16))
        style.configure("Section.TLabel", background="#111827", foreground="#93c5fd", font=("Segoe UI Semibold", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 6))
        style.configure("Accent.TButton", font=("Segoe UI Semibold", 10), padding=(10, 6))
        style.configure("TNotebook", background="#111827", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(12, 7), font=("Segoe UI", 10))

        root = ttk.Panedwindow(self, orient="horizontal")
        root.pack(fill="both", expand=True, padx=12, pady=12)

        self.left = ttk.Frame(root, width=520)
        self.right = ttk.Frame(root)
        root.add(self.left, weight=0)
        root.add(self.right, weight=1)

        self._build_left()
        self._build_right()

    def _build_left(self):
        header = ttk.Frame(self.left)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="ICC Controller", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="Simple control panel and live heat map.").pack(anchor="w")

        serial_card = ttk.Frame(self.left)
        serial_card.pack(fill="x", pady=(0, 10))
        serial_card.columnconfigure(1, weight=0)  # Keep the port combobox narrow: do not let column 1 expand

        ttk.Label(serial_card, text="Port").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=6)
        self.port_combo = ttk.Combobox(serial_card, textvariable=self.port_var, state="readonly", width=6)
        self.port_combo.grid(row=0, column=1, sticky="w", pady=6)  # align left and avoid stretching
        ttk.Button(serial_card, text="Refresh", command=self._refresh_ports).grid(row=0, column=2, padx=6, pady=6)
        self.connect_btn = ttk.Button(serial_card, text="Connect", style="Accent.TButton", command=self._toggle_connection)
        self.connect_btn.grid(row=0, column=3, pady=6)

        ttk.Label(serial_card, text="Status").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(0, 8))
        ttk.Label(serial_card, textvariable=self.status_var).grid(row=1, column=1, columnspan=3, sticky="w", pady=(0, 8))

        notebook = ttk.Notebook(self.left)
        notebook.pack(fill="both", expand=True)
        self.icc_tab = ttk.Frame(notebook)
        self.path_tab = ttk.Frame(notebook)
        notebook.add(self.icc_tab, text="ICC")
        notebook.add(self.path_tab, text="Path")

        self._build_icc_tab()
        self._build_path_tab()

    def _build_icc_tab(self):
        top = ttk.Frame(self.icc_tab)
        top.pack(fill="x", padx=8, pady=8)
        ttk.Label(top, text="Rows").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(top, from_=1, to=MAX_ROWS, width=5, textvariable=self.rows_var).grid(row=0, column=1, padx=(6, 14), sticky="w")
        ttk.Label(top, text="Cols").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(top, from_=1, to=MAX_COLS, width=5, textvariable=self.cols_var).grid(row=0, column=3, padx=(6, 14), sticky="w")
        ttk.Label(top, text="Time step (ms)").grid(row=0, column=4, sticky="w")
        ttk.Spinbox(top, from_=1, to=60000, width=7, textvariable=self.time_step_var).grid(row=0, column=5, padx=(6, 14), sticky="w")
        ttk.Button(top, text="Apply", command=self._rebuild_grids).grid(row=0, column=6, sticky="w")

        ttk.Label(top, text="All ICC Freq").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Combobox(top, state="readonly", values=[str(f) for f in SUPPORTED_FREQS], width=4, textvariable=self.icc_freq_all_var).grid(row=1, column=1, padx=(6, 14), pady=(10, 0), sticky="w")
        ttk.Button(top, text="Apply All", command=self._apply_all_icc_freqs).grid(row=1, column=2, columnspan=2, sticky="w", pady=(10, 0))

        self.icc_frame = ttk.Frame(self.icc_tab)
        self.icc_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _build_path_tab(self):
        top = ttk.Frame(self.path_tab)
        top.pack(fill="x", padx=8, pady=8)
        ttk.Label(top, text="All Path Delay (ms)").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(top, from_=0, to=UINT16_MAX, width=4, textvariable=self.path_delay_all_var).grid(row=0, column=1, padx=(6, 12), sticky="w")
        ttk.Button(top, text="Apply All", command=self._apply_all_path_delays).grid(row=0, column=2, sticky="w")
        self.path_frame = ttk.Frame(self.path_tab)
        self.path_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _build_viewer_options(self, parent=None):
        if parent is None:
            parent = self.left
        card = ttk.Frame(parent)
        card.pack(fill="x", pady=(10, 0))
        card.columnconfigure(1, weight=1)
        card.columnconfigure(4, weight=1)

        ttk.Label(card, text="Viewer Range", style="Section.TLabel").grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))
        ttk.Label(card, text="V min").grid(row=1, column=0, sticky="w")
        ttk.Entry(card, width=10, textvariable=self.v_min_var).grid(row=1, column=1, sticky="w")
        ttk.Label(card, text="V max").grid(row=1, column=2, sticky="w")
        ttk.Entry(card, width=10, textvariable=self.v_max_var).grid(row=1, column=3, sticky="w")

        ttk.Label(card, text="Low color").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.low_color_btn = ttk.Button(card, text=self.low_color_var.get(), command=self._pick_low_color)
        self.low_color_btn.grid(row=2, column=1, sticky="w", pady=(6, 0))
        self.low_color_swatch = tk.Canvas(card, width=18, height=18, highlightthickness=1, highlightbackground="#94a3b8")
        self.low_color_swatch.grid(row=2, column=2, sticky="w", padx=(8, 0), pady=(6, 0))
        ttk.Label(card, text="High color").grid(row=2, column=3, sticky="w", pady=(6, 0))
        self.high_color_btn = ttk.Button(card, text=self.high_color_var.get(), command=self._pick_high_color)
        self.high_color_btn.grid(row=2, column=4, sticky="w", pady=(6, 0))
        self.high_color_swatch = tk.Canvas(card, width=18, height=18, highlightthickness=1, highlightbackground="#94a3b8")
        self.high_color_swatch.grid(row=2, column=5, sticky="w", padx=(8, 0), pady=(6, 0))

        self._update_color_swatches()

    def _build_right(self):
        ttk.Label(self.right, text="Realtime ICC Activity Viewer", style="Title.TLabel").pack(anchor="w", pady=(0, 8))
        container = ttk.Frame(self.right)
        container.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(container, bg="#f8fafc", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._draw_heatmap())

        # place viewer options below the canvas
        self._build_viewer_options(parent=container)

    def _refresh_ports(self):
        ports = [p.device for p in list_ports.comports()]
        self.port_combo["values"] = ports
        if ports and not self.port_var.get():
            self.port_var.set(ports[0])

    def _toggle_connection(self):
        if self.connected:
            self._disconnect()
            return

        port = self.port_var.get().strip()
        if not port:
            messagebox.showwarning("No port", "Pick a serial port first.")
            return

        try:
            settings = self._collect_settings()
        except ValueError as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return

        self.reader = SerialReader(
            port,
            settings,
            on_frame=self._on_frame,
            on_status=self._set_status,
            on_error=self._on_error,
            icc_vars=self.icc_vars,
            path_vars=self.path_vars,
        )
        self.reader.start()
        self.connected = True
        self.connect_btn.configure(text="Disconnect")
        self._set_status(f"Connecting to {port}...")

    def _disconnect(self):
        if self.reader is not None:
            self.reader.stop()
            self.reader = None
        self.connected = False
        self.connect_btn.configure(text="Connect")
        self._set_status("Disconnected")

    def _collect_settings(self) -> Settings:
        rows = clamp_int(self.rows_var.get(), 1, MAX_ROWS)
        cols = clamp_int(self.cols_var.get(), 1, MAX_COLS)
        if rows * cols > MAX_TOTAL_CELLS:
            raise ValueError("Grid must be 25 cells or fewer on the Uno.")

        v_min = float(self.v_min_var.get())
        v_max = float(self.v_max_var.get())
        if v_max <= v_min:
            raise ValueError("V max must be greater than V min.")

        return Settings(
            rows=rows,
            cols=cols,
            time_step_ms=clamp_int(self.time_step_var.get(), 1, 60000),
            icc_freq=clamp_int(self.icc_freq_all_var.get(), min(SUPPORTED_FREQS), max(SUPPORTED_FREQS)),
            path_delay_ms=clamp_int(self.path_delay_all_var.get(), 0, 65535),
            v_min=v_min,
            v_max=v_max,
            low_color=self.low_color_var.get(),
            high_color=self.high_color_var.get(),
        )

    def _rebuild_grids(self):
        self.settings.rows = clamp_int(self.rows_var.get(), 1, MAX_ROWS)
        self.settings.cols = clamp_int(self.cols_var.get(), 1, MAX_COLS)
        self.values = [self.settings.v_min] * (self.settings.rows * self.settings.cols)
        self._build_icc_grid()
        self._build_path_grid()
        self._draw_heatmap()

    def _build_icc_grid(self):
        for child in self.icc_frame.winfo_children():
            child.destroy()

        rows = self.rows_var.get()
        cols = self.cols_var.get()
        self.icc_vars = []
        ttk.Label(self.icc_frame, text="ICC Frequency Matrix", style="Section.TLabel").grid(row=0, column=0, columnspan=cols + 1, sticky="w", pady=(0, 8))
        ttk.Label(self.icc_frame, text="").grid(row=1, column=0)
        for c in range(cols):
            ttk.Label(self.icc_frame, text=f"C{c + 1}").grid(row=1, column=c + 1)

        for r in range(rows):
            ttk.Label(self.icc_frame, text=f"R{r + 1}").grid(row=r + 2, column=0, sticky="e")
            row_vars: list[tk.StringVar] = []
            for c in range(cols):
                var = tk.StringVar(value=str(self.icc_freq_all_var.get()))
                ttk.Combobox(self.icc_frame, values=[str(f) for f in SUPPORTED_FREQS], state="readonly", width=4, textvariable=var).grid(row=r + 2, column=c + 1, padx=2, pady=2)
                row_vars.append(var)
            self.icc_vars.append(row_vars)

    def _build_path_grid(self):
        for child in self.path_frame.winfo_children():
            child.destroy()

        rows = self.rows_var.get()
        cols = self.cols_var.get()
        h_cols = max(cols - 1, 0)
        v_rows = max(rows - 1, 0)
        self.path_vars = []

        ttk.Label(self.path_frame, text="Path Delay Matrix", style="Section.TLabel").grid(row=0, column=0, columnspan=max(1, cols), sticky="w", pady=(0, 8))
        if h_cols == 0:
            ttk.Label(self.path_frame, text="No horizontal paths for a 1-column grid.").grid(row=1, column=0, sticky="w")
        else:
            ttk.Label(self.path_frame, text="Horizontal").grid(row=1, column=0, sticky="w")
            for c in range(h_cols):
                ttk.Label(self.path_frame, text=f"C{c + 1}->{c + 2}").grid(row=1, column=c + 1)
            for r in range(rows):
                ttk.Label(self.path_frame, text=f"R{r + 1}").grid(row=r + 2, column=0, sticky="e")
                row_vars: list[tk.StringVar] = []
                for c in range(h_cols):
                    var = tk.StringVar(value=str(self.path_delay_all_var.get()))
                    ttk.Spinbox(self.path_frame, from_=0, to=65535, width=4, textvariable=var).grid(row=r + 2, column=c + 1, padx=2, pady=2)
                    row_vars.append(var)
                self.path_vars.append(row_vars)

        y = rows + 4
        if v_rows == 0:
            ttk.Label(self.path_frame, text="No vertical paths for a 1-row grid.").grid(row=y, column=0, sticky="w", pady=(12, 0))
        else:
            ttk.Label(self.path_frame, text="Vertical").grid(row=y, column=0, sticky="w", pady=(12, 0))
            for c in range(cols):
                ttk.Label(self.path_frame, text=f"C{c + 1}").grid(row=y, column=c + 1)
            for r in range(v_rows):
                ttk.Label(self.path_frame, text=f"R{r + 1}->{r + 2}").grid(row=y + 1 + r, column=0, sticky="e")
                row_vars: list[tk.StringVar] = []
                for c in range(cols):
                    var = tk.StringVar(value=str(self.path_delay_all_var.get()))
                    ttk.Spinbox(self.path_frame, from_=0, to=65535, width=4, textvariable=var).grid(row=y + 1 + r, column=c + 1, padx=2, pady=2)
                    row_vars.append(var)
                self.path_vars.append(row_vars)

    def _apply_all_icc_freqs(self):
        freq = clamp_int(self.icc_freq_all_var.get(), min(SUPPORTED_FREQS), max(SUPPORTED_FREQS))
        self.icc_freq_all_var.set(freq)
        for row in self.icc_vars:
            for var in row:
                var.set(str(freq))

    def _apply_all_path_delays(self):
        delay = clamp_int(self.path_delay_all_var.get(), 0, 65535)
        self.path_delay_all_var.set(delay)
        for row in self.path_vars:
            for var in row:
                var.set(str(delay))

    def _pick_low_color(self):
        result = colorchooser.askcolor(color=self.low_color_var.get(), title="Pick low color")
        if result and result[1]:
            self.low_color_var.set(result[1])
            self.low_color_btn.configure(text=result[1])
            self._update_color_swatches()

    def _pick_high_color(self):
        result = colorchooser.askcolor(color=self.high_color_var.get(), title="Pick high color")
        if result and result[1]:
            self.high_color_var.set(result[1])
            self.high_color_btn.configure(text=result[1])
            self._update_color_swatches()

    def _update_color_swatches(self):
        if hasattr(self, "low_color_swatch"):
            self.low_color_swatch.delete("all")
            self.low_color_swatch.create_rectangle(0, 0, 18, 18, fill=self.low_color_var.get(), outline="")
        if hasattr(self, "high_color_swatch"):
            self.high_color_swatch.delete("all")
            self.high_color_swatch.create_rectangle(0, 0, 18, 18, fill=self.high_color_var.get(), outline="")

    def _on_frame(self, values: list[float]):
        self.values = values
        self.after(0, self._draw_heatmap)

    def _on_error(self, message: str):
        self.after(0, lambda: messagebox.showerror("Serial error", message))
        self.after(0, self._disconnect)

    def _set_status(self, message: str):
        self.after(0, lambda: self.status_var.set(message))

    def _draw_heatmap(self):
        self.canvas.delete("all")
        rows = max(1, self.rows_var.get())
        cols = max(1, self.cols_var.get())
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        size = min(width / cols, height / rows)
        left = (width - (size * cols)) / 2
        top = (height - (size * rows)) / 2
        v_min = float(self.v_min_var.get())
        v_max = float(self.v_max_var.get())
        span = v_max - v_min if v_max > v_min else 1.0
        low_rgb = hex_to_rgb(self.low_color_var.get())
        high_rgb = hex_to_rgb(self.high_color_var.get())

        for r in range(rows):
            for c in range(cols):
                idx = r * cols + c
                value = self.values[idx] if idx < len(self.values) else v_min
                t = clamp((value - v_min) / span, 0.0, 1.0)
                fill = rgb_to_hex(mix_rgb(low_rgb, high_rgb, t))
                x1 = left + c * size
                y1 = top + r * size
                x2 = x1 + size
                y2 = y1 + size
                self.canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline="#dbe4f0")

    def _tick(self):
        self._draw_heatmap()
        self.after(40, self._tick)

    def on_close(self):
        self._disconnect()
        self.destroy()


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        return (255, 255, 255)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{max(0, min(255, c)):02x}" for c in rgb)


def mix_rgb(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    """Linearly interpolate between two RGB triples by t in [0.0, 1.0]."""
    t = clamp(t, 0.0, 1.0)
    return (
        int(round(a[0] + (b[0] - a[0]) * t)),
        int(round(a[1] + (b[1] - a[1]) * t)),
        int(round(a[2] + (b[2] - a[2]) * t)),
    )


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def clamp_int(value, lo: int, hi: int) -> int:
    try:
        value = int(value)
    except Exception:
        value = lo
    return max(lo, min(hi, value))


def main():
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()