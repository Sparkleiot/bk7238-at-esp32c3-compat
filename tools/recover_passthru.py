#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Recover a module that is stuck in AT passthrough (CIPMODE=1 + CIPSEND handed UART to net).

Sequence: guard time -> "+++" -> AT -> ATE0 -> CIPMODE=0 -> close all links.
Idempotent and safe on a healthy module too.
"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else 'COM5'


def raw(s, data, wait):
    s.reset_input_buffer()
    s.write(data)
    time.sleep(wait)
    return s.read(1024).decode('utf-8', 'replace')


def cmd(s, c, wait=1.0):
    return ' | '.join(l.strip() for l in raw(s, (c + '\r\n').encode(), wait).replace('\r', '').split('\n') if l.strip())


def main():
    s = serial.Serial(PORT, 115200, timeout=0.3)
    try:
        time.sleep(0.2)
        s.reset_input_buffer()
        # 1s guard so the module's escape detector sees a quiet gap before "+++"
        s.write(b'\r\n\r\n')
        time.sleep(1.2)
        print('  +++      -> %r' % raw(s, b'+++', 1.5).strip())
        print('  AT       -> %s' % cmd(s, 'AT', 1.5))
        print('  ATE0     -> %s' % cmd(s, 'ATE0', 1.0))
        print('  CIPMODE=0-> %s' % cmd(s, 'AT+CIPMODE=0', 1.5))
        print('  CLOSE=5  -> %s' % cmd(s, 'AT+CIPCLOSE=5', 2.0))
        print('  CWMODE?  -> %s' % cmd(s, 'AT+CWMODE?', 1.0))
        print('  CWJAP?   -> %s' % cmd(s, 'AT+CWJAP?', 1.5))
        print('  CIFSR    -> %s' % cmd(s, 'AT+CIFSR', 1.5))
    finally:
        s.close()


if __name__ == '__main__':
    main()