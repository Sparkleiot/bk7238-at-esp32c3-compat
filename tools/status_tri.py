#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Fast health/state probe of the three BK7238 modules (COM5/COM6/COM7).

Prints, per port: AT alive?, CIPMODE, CWMODE, CWJAP/CIPSTA, CIFSR.
Silences echo first (ATE0) to avoid the UART1 interleaving problem.
"""
import sys
import time

import serial

PORTS = sys.argv[1:] or ['COM5', 'COM6', 'COM7']
CMDS = ['AT', 'AT+CIPMODE?', 'AT+CWMODE?', 'AT+CWJAP?', 'AT+CIFSR']


def xchg(s, cmd, wait=0.9):
    s.reset_input_buffer()
    s.write((cmd + '\r\n').encode())
    time.sleep(wait)
    raw = s.read(512)
    txt = raw.decode('utf-8', 'replace')
    lines = [ln.strip() for ln in txt.replace('\r', '').split('\n')]
    lines = [ln for ln in lines if ln]
    return lines


def main():
    for port in PORTS:
        print('=== %s ===' % port)
        try:
            s = serial.Serial(port, 115200, timeout=0.3)
        except Exception as e:
            print('  OPEN FAIL: %r' % (e,))
            continue
        try:
            time.sleep(0.2)
            xchg(s, 'ATE0')
            for c in CMDS:
                print('  %-16s -> %s' % (c, ' | '.join(xchg(s, c))))
        finally:
            s.close()
        print()


if __name__ == '__main__':
    main()
