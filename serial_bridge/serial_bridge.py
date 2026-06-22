#!/usr/bin/env python3
"""Bidirectionally relay raw serial bytes between two COM ports."""

import argparse
import sys
import time

import serial


def parse_args():
    parser = argparse.ArgumentParser(
        description="Relay raw bytes bidirectionally between two serial ports.")
    parser.add_argument("--port-a", default="COM5",
                        help="First serial port, e.g. COM5")
    parser.add_argument("--port-b", default="COM9",
                        help="Second serial port, e.g. COM9")
    parser.add_argument("--baud", type=int, default=115200,
                        help="Baud rate for both ports")
    parser.add_argument("--chunk-size", type=int, default=1024,
                        help="Maximum bytes to read per loop")
    return parser.parse_args()


def main():
    args = parse_args()

    try:
        with serial.Serial(args.port_a, args.baud, timeout=0.01) as port_a, \
                serial.Serial(args.port_b, args.baud, timeout=0.01) as port_b:
            print(
                f"Relaying {args.port_a} <-> {args.port_b} "
                f"at {args.baud} baud. Press Ctrl+C to stop.")

            while True:
                moved = False

                data = port_a.read(args.chunk_size)
                if data:
                    port_b.write(data)
                    port_b.flush()
                    moved = True

                data = port_b.read(args.chunk_size)
                if data:
                    port_a.write(data)
                    port_a.flush()
                    moved = True

                if not moved:
                    time.sleep(0.001)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    except serial.SerialException as exc:
        print(f"Serial error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
