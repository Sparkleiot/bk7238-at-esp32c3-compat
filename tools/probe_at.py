#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Probe a WB3S/BK7238 module on a serial port: read boot log, send AT commands."""
import argparse
import sys
import time

import serial


def clean(b: bytes) -> str:
    out = []
    i = 0
    while i < len(b):
        c = b[i]
        if c == 0x1B:  # ESC - skip ANSI sequence
            i += 1
            while i < len(b) and not (0x40 <= b[i] <= 0x7E):
                i += 1
            i += 1
            continue
        if c == 0:
            i += 1
            continue
        out.append(chr(c) if 0x20 <= c <= 0x7E or c in (10, 13, 9) else '.')
        i += 1
    return ''.join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('port', nargs='?', default='COM3')
    ap.add_argument('baud', nargs='?', type=int, default=115200)
    ap.add_argument('--listen', type=float, default=2.0)
    ap.add_argument('--cmds', default='AT,AT+GMR,AT+CWMODE?,AT+CIFSR')
    args = ap.parse_args()

    s = serial.Serial(args.port, args.baud, timeout=0.2)
    print('[open] %s @%d' % (args.port, args.baud))

    t0 = time.time()
    buf = b''
    while time.time() - t0 < args.listen:
        d = s.read(8192)
        if d:
            buf += d
    print('--- boot/passive (%d bytes) ---' % len(buf))
    print(clean(buf))

    for cmd in [c for c in args.cmds.split(',') if c]:
        s.reset_input_buffer()
        s.write((cmd + '\r\n').encode())
        time.sleep(0.6)
        r = s.read(8192)
        print('>>> %-20s <= %s' % (cmd, repr(clean(r))))
    s.close()


if __name__ == '__main__':
    sys.exit(main())
