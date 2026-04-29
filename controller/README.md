# ICC Board Controller

Desktop GUI for configuring, initialising, and visualising an ICC (Interstitial Cells of Cajal) network running on an Arduino Mega 2560.

---

## Requirements

| Dependency  | Install                                  |
| ----------- | ---------------------------------------- |
| Python 3.9+ | [python.org](https://www.python.org)     |
| pyserial    | `pip install pyserial`                   |
| tkinter     | Included with standard Python on Windows |

---

## Running from source

```powershell
pip install pyserial
python controller.py
```

## Building a standalone executable

The `controller.spec` file is already configured for PyInstaller.

```powershell
pip install pyinstaller
pyinstaller controller.spec
```

The executable is output to `dist/controller.exe`. It requires no Python installation to run.

---

## UI overview

### Theme

A **Theme** dropdown at the top of the left panel switches between **Dark** and **Light** colour schemes. All panels, the live viewer, and the colour swatches update immediately.

---

### Connection

| Control              | Purpose                                                      |
| -------------------- | ------------------------------------------------------------ |
| Port dropdown + ⟳    | Select the COM port; refresh the list                        |
| Connect / Disconnect | Opens or closes the serial port and resets the board via DTR |

After connecting the app holds for 2.5 s while the board boots, then enables **Initialize Board**.

---

### ICC Grid Settings

All grid configuration is grouped here.

#### Initialize Board

Sends the ICCF init packet to the board with the current settings. Must be clicked after every settings change to take effect on hardware.

#### General

| Field         | Description                                                  |
| ------------- | ------------------------------------------------------------ |
| Rows / Cols   | Grid dimensions (1–10 each)                                  |
| Timestep (ms) | Simulation step size sent to the board                       |
| Save / Load   | Save or load the full grid configuration to/from a JSON file |

#### Slow-Wave Intervals (s)

Sets the autonomous pacemaking period for each cell. The **All cells / Apply** shortcut fills every cell at once.

| Value | Behaviour                                                               |
| ----- | ----------------------------------------------------------------------- |
| `-1`  | **Blocked** — stays in Q0 resting, ignores relay signals completely     |
| `0`   | **Follower** — no resting slope; fires only when a relay signal arrives |
| `15`  | Pacemaker, ~15 s period                                                 |
| `20`  | Pacemaker, ~20 s period                                                 |
| `23`  | Pacemaker, ~23 s period                                                 |
| `26`  | Pacemaker, ~26 s period                                                 |
| `30`  | Pacemaker, ~30 s period                                                 |
| `40`  | Pacemaker, ~40 s period                                                 |

> Note: 10 s and below are not achievable with the current model — the fixed Q1+Q2+Q3 phases consume ~10.8 s per cycle.

#### H-Path Delays (ms) / V-Path Delays (ms)

Conduction delay on each horizontal or vertical path between adjacent cells. The **All H-paths / All V-paths** spinboxes with **Apply** fill all paths at once.

---

### Live ICC Activity Viewer

Real-time heatmap of cell voltages. The canvas resizes automatically when the grid dimensions change or a new configuration is initialised.

- Row and column indices are shown on the axes.
- Active cells are coloured by voltage (Low → High colour gradient).
- Blocked cells (`-1`) show the **Blocked cell color**.
- Cells outside the configured grid show the **inactive** colour or are hidden.

---

### Live Viewer Settings

| Control                 | Description                                                        |
| ----------------------- | ------------------------------------------------------------------ |
| **Show values**         | Overlay the voltage number on each cell                            |
| **Show colors**         | Enable the voltage heat-map colouring                              |
| **Show grid**           | Draw outlines between cells                                        |
| **Show inactive cells** | Show/hide cells outside the configured grid and `-1` blocked cells |
| **V min / V max**       | Voltage range mapped to the Low/High colour gradient               |
| **Low color**           | Colour at V min                                                    |
| **High color**          | Colour at V max                                                    |
| **Value text color**    | Colour of the voltage number overlay                               |
| **Background color**    | Cell fill when **Show colors** is off                              |
| **Blocked cell color**  | Flat fill for `-1` blocked cells                                   |

---

## Serial protocol

### Init packet (PC → board)

Sent when **Initialize Board** is clicked.

| Bytes               | Field                                               |
| ------------------- | --------------------------------------------------- |
| `49 43 43 46`       | ASCII header `ICCF`                                 |
| 1                   | rows (uint8)                                        |
| 1                   | cols (uint8)                                        |
| 2                   | timestep ms (uint16 LE)                             |
| rows × cols         | per-cell interval (int8, row-major)                 |
| rows × (cols−1) × 2 | H-path delays (uint16 LE each), omitted if cols = 1 |
| (rows−1) × cols × 2 | V-path delays (uint16 LE each), omitted if rows = 1 |

### Telemetry packet (board → PC)

Sent every timestep while running.

| Bytes           | Field                                 |
| --------------- | ------------------------------------- |
| `AA 55`         | Sync header                           |
| rows × cols × 4 | cell voltages (float32 LE, row-major) |

A cell voltage of exactly `0.0` indicates the WAIT state.

---

## Save / Load file format

Settings are stored as JSON:

```json
{
  "rows": 10,
  "cols": 10,
  "step_ms": 200,
  "intervals": [[0, 20, ...], ...],
  "h_delays": [[1000, ...], ...],
  "v_delays": [[1000, ...], ...]
}
```
