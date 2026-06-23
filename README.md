# embedded-icc-uno

Arduino Mega 2560 implementation of the ICC (Interstitial Cells of Cajal) network model — up to a 5×5 grid of cells with configurable pacemaker intervals, conduction delays, and path gaps.

---

## Repository layout

```
src/
  main.cpp       — Arduino runtime: serial init, network step loop, telemetry
  icc.c          — ICC cell state machine (Q0–Q3 + WAIT)
  path.c         — IccPath relay model between neighbouring cells
  egm.c          - Path dipole and electrode potential calculation
include/
  icc.h          — Icc struct, constants, and API
  path.h         — IccPath struct and API
  egm.h          - PathDipole and Electrode structs and API
controller/
  controller.py  — Desktop GUI (Python/Tkinter)
  controller.spec
  README.md      — Full controller documentation
```

---

## Controller app

A desktop GUI for configuring, initialising, and visualising the ICC network in real time.

See [controller/README.md](controller/README.md) for full documentation.

**Quick start:**

```powershell
pip install pyserial
python controller/controller.py
```

**Standalone executable (no Python required):**

```powershell
pip install pyinstaller
pyinstaller controller/controller.spec
# Output: controller/dist/icc-controller.exe
```

---

## Firmware

### Build and upload (PlatformIO)

```powershell
py -m platformio run
py -m platformio run --target upload
```

### Serial monitor

```powershell
py -m platformio device monitor --baud 115200
```

The firmware does **not** print human-readable text during normal operation. Use the controller app (or any tool that speaks the binary protocol below) to interact with it.

---

## Source overview

### `src/icc.c` — Cell state machine

Each ICC cell cycles through five states:

| State | Description |
|---|---|
| `WAIT` | 5 s startup delay before the cell becomes active |
| `Q0_RESTING` | Resting; slow downward drift toward the Q1 threshold (pacemakers only) |
| `Q1_UPSTROKE` | Rapid depolarisation |
| `Q2_PLATEAU` | Plateau phase |
| `Q3_REPOLARIZATION` | Repolarisation back toward rest |

**Cell types** (set by `pm_sw_interval` passed to `icc_init`):

| Interval | Type | Behaviour |
|---|---|---|
| `-1` | Blocked | Stays in Q0_RESTING; absorbs any relay signal without firing |
| `0` | Follower | No resting slope; fires only when a relay signal arrives |
| `15`–`40` | Pacemaker | Autonomous slow-wave at the given approximate period (seconds) |

> Note: periods of 10 s and below are not achievable — the fixed Q1+Q2+Q3 phases consume approximately 10.8 s per cycle.

### `src/path.c` — Conduction paths

`IccPath` connects two adjacent cells. When the upstream cell fires, the path starts a timed relay that triggers the downstream cell after the configured delay.

### `src/egm.c` - EGM path dipoles and electrodes

Each path has a `PathDipole` that is active while propagation is travelling across that path. Each configured `Electrode` stores a grid position, height above the tissue plane, and the summed potential contribution from all active path dipoles.

### `src/main.cpp` — Runtime

- Waits for an `ICCF` init packet over serial before starting.
- Unpacks rows, cols, timestep, per-cell intervals, path delays, path gaps, and electrode definitions from the packet.
- Runs `step_icc_network_1d()` at the configured timestep and streams a binary telemetry packet after each step.
- Sends an EGM-only packet on Mega `Serial1` for the pacemaker interface.

---

## Serial protocol

### Init packet (PC → board)

| Bytes | Field |
|---|---|
| `49 43 43 46` | ASCII header `ICCF` |
| 1 | rows (uint8) |
| 1 | cols (uint8) |
| 2 | timestep ms (uint16 LE) |
| rows × cols | per-cell interval (int8, row-major) |
| rows × (cols−1) × 2 | H-path delays (uint16 LE each), omitted if cols = 1 |
| (rows−1) × cols × 2 | V-path delays (uint16 LE each), omitted if rows = 1 |
| rows × (cols−1) | H-path gaps in mm (uint8 each), omitted if cols = 1 |
| (rows−1) × cols | V-path gaps in mm (uint8 each), omitted if rows = 1 |
| 1 | electrode count (uint8) |
| electrode count × 3 | electrode row, column, and height in mm (uint8 each) |
| 1 | GES sensing electrode enabled (uint8, 0 or 1) |
| 1 | GES sensing electrode index (uint8, into electrode list) |
| 1 | pacing lead enabled (uint8, 0 or 1) |
| 1 | pacing lead row (uint8) |
| 1 | pacing lead column (uint8) |

### Telemetry packet (board → PC)

Sent every timestep while running.

| Bytes | Field |
|---|---|
| `AA 55` | Sync header |
| rows × cols × 4 | cell voltages (float32 LE, row-major) |
| electrode count × 4 | EGM potentials (float32 LE, initialization order) |

A cell voltage of exactly `0.0` indicates the WAIT state.

### Pacemaker EGM sample (board to pacemaker, Serial1)

Sent every timestep on Mega `Serial1` at 115200 baud. `Serial1` uses TX1 pin 18 and RX1 pin 19; the current firmware writes this sample to TX1. The sample is the configured GES sensing electrode potential multiplied by 1000, clamped to `int16_t`, and sent little-endian.

| Bytes | Field |
|---|---|
| 2 | EGM sample (int16 LE, GES sensing electrode potential x 1000) |

Incoming pacemaker pacing bytes are read from `Serial1` RX1. A byte value of `1` stimulates the configured pacing lead location from the init packet.

---

## Hardware

Targets **Arduino Mega 2560** (ATmega2560, 8 KB SRAM). The compile-time network limit is 5×5 to leave working memory for path dipoles, electrodes, serial processing, and the runtime stack.

