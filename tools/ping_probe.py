#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Characterise AT+PING on a BK7238 module.

Sends a sequence of AT+PING targets and prints the raw reply, with timing.
Also (optionally) does a PC -> module ping to check the module's ICMP *reply* path.
"""
import subprocess
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else 'COM5'
MODIP = sys.argv[2] if len(sys.argv) > 2 else '192.168.0.163'

TARGETS = [
    '192.168.0.1',        # gateway of MyHomeWiFi (same wifi module uses)
    '192.168.0.152',      # PC (expected: firewall drops)
    '8.8.8.8',            # public
    'www.baidu.com',      # DNS + ping
]


def xchg(s, cmd, wait=3.0):
    s.reset_input_buffer()
    t0 = time.time()
    s.write((cmd + '\r\n').encode())
    time.sleep(wait)
    raw = s.read(1024)
    dt = time.time() - t0
    txt = raw.decode('utf-8', 'replace')
    lines = [ln.strip() for ln in txt.replace('\r', '').split('\n') if ln.strip()]
    return dt, lines


def main():
    s = serial.Serial(PORT, 115200, timeout=0.3)
    try:
        time.sleep(0.2)
        xchg(s, 'ATE0', 0.6)
        print('--- module state ---')
        for c in ('AT+CWMODE?', 'AT+CIFSR', 'AT+CIPSTA?'):
            print('  %-14s -> %s' % (c, ' | '.join(xchg(s, c)[1])))

        print('\n--- AT+PING (from module) ---')
        for t in TARGETS:
            dt, lines = xchg(s, 'AT+PING="%s"' % t, 3.0)
            print('  %-18s [%.2fs] -> %s' % (t, dt, ' | '.join(lines)))

        print('\n--- PC -> module ping (module reply path) ---')
        try:
            out = subprocess.run(['ping', '-n', '3', '-w', '1000', MODIP],
                                 capture_output=True, timeout=15)
            print(out.stdout.decode('gbk', 'replace').strip())
        except Exception as e:
            print('  ping failed: %r' % (e,))
    finally:
        s.close()


if __name__ == '__main__':
    main()
