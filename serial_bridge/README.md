# Serial Bridge

Relays raw bytes bidirectionally between two serial ports. This is useful for
connecting the Mega EGM stream on `COM5` and a DE1-SoC HPS serial port on
`COM9`.

## Install

```powershell
pip install pyserial
```

## Run

Default ports:

```powershell
python serial_bridge.py
```

Equivalent explicit command:

```powershell
python serial_bridge.py --port-a COM5 --port-b COM9 --baud 115200
```

The bridge forwards bytes unchanged in both directions, including the EGM packet
header and sample:

```text
AA 55 + int16 sample
```

Only one program can open a COM port at a time. Close Simulink or the controller
if they are already using `COM5` or `COM9`.
