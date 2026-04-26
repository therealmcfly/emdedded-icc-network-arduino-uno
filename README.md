# embedded-icc-uno

Arduino Uno implementation of the ICC model based on StudyProject ICC and path setup patterns.

## What is included

- include/icc.h and src/icc.c: ICC cell state machine model.
- include/path.h and src/path.c: path relay model between neighboring ICC cells.
- src/main.cpp: Uno runtime setup and periodic stepping.

## Current setup in src/main.cpp

The current configuration is single ICC mode:

- ICC_V_COUNT = 1
- ICC_H_COUNT = 1
- pacemaker at row 0, col 0
- TIME_STEP_MS_1D = 200 ms

With one cell, there are no active neighbor paths, so only the single ICC state and voltage evolve.

## Scaling to multiple ICC cells

You can scale by changing the grid size macros in src/main.cpp.

### 1x5 (one row, five cells)

- Set ICC_V_COUNT = 1
- Set ICC_H_COUNT = 5
- Set pacemaker location, for example:
  - PACEMAKER_CELL_ROW = 0
  - PACEMAKER_CELL_COL = 4

This case is already supported by the current horizontal path code in src/main.cpp.

### 5x5 or 10x10 (multi-row grid)

For ICC_V_COUNT > 1, update src/main.cpp to include vertical paths as well as horizontal paths.

Required additions:

- Vertical path storage:
  - IccPath v_paths[ICC_V_COUNT - 1][ICC_H_COUNT];
  - float v_path_t1[ICC_V_COUNT - 1][ICC_H_COUNT];
  - float v_path_t2[ICC_V_COUNT - 1][ICC_H_COUNT];
- Vertical path init loop:
  - connect cells (i,j) to (i+1,j)
- Vertical path update loop in each time step

Without vertical paths, rows are not connected to each other.

### Example macro sets

1x5:

- ICC_V_COUNT = 1
- ICC_H_COUNT = 5

5x5:

- ICC_V_COUNT = 5
- ICC_H_COUNT = 5

10x10:

- ICC_V_COUNT = 10
- ICC_H_COUNT = 10

### Performance note on Uno

Arduino Uno has limited RAM, so 5x5 and especially 10x10 may be too large depending on logging and extra arrays.
If memory becomes an issue:

- reduce logging output
- reduce stored timing arrays
- test first with 1x5, then 3x3, then 5x5
- use a board with more RAM (for example, Mega) for large grids

## Enable print logs

In src/main.cpp, inside loop(), make sure this line is enabled:

```cpp
print_telemetry();
```

If it is commented as shown below, remove the comment marks:

```cpp
// print_telemetry();
```

## Flash to Uno (Windows PowerShell)

Run from the embedded-icc-uno folder:

```powershell
py -m platformio run
py -m platformio run --target upload
```

## See logs from the board

Open serial monitor at 115200 baud:

```powershell
py -m platformio device monitor --baud 115200
```

If needed, specify port explicitly:

```powershell
py -m platformio device list
py -m platformio device monitor --port COM3 --baud 115200
```

Expected output format per step:

```text
sample=123 ms=45678 v=[-63.217] s=[0] p=[] t1=[] t2=[]
```

Notes:

- If monitor opens but no data appears, press the Uno reset button once.
- Only one app can use the COM port at a time; close other serial monitors first.
