#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Ping a matrix of LAN targets from the module to find the failure boundary.

Also tries a repeat of the gateway ping (intermittency check) and a self-ping.
"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else 'COM5'

# gateway first, then a spread of LAN hosts seen in the PC ARP table, then self, then WAN
TARGETS = [
    '192.168.0.1',    # gateway
    '192.168.0.1',    # gateway again (intermittent?)
    '192.168.0.34',
    '192.168.0.139',
    '192.168.0.151',
    '192.168.0.187',
    '192.168.0.164',
    '192.168.0.173',
    '192.168.0.163',  # self
    '1.1.1.1',
    '8.8.8.8',
]


def xchg(s, cmd, wait=3.2):
    s.reset_input_buffer()
    s.write((cmd + '\r\n').encode())
    time.sleep(wait)
    raw = s.read(1024)
    return [ln.strip() for ln in raw.decode('utf-8', 'replace').replace('\r', '').split('\n') if ln.strip()]


def main():
    s = serial.Serial(PORT, 115200, timeout=0.3)
    try:
        time.sleep(0.2)
        xchg(s, 'ATE0', 0.6)
        for t in TARGETS:
            print('  %-16s -> %s' % (t, ' '.join(xchg(s, 'AT+PING="%s"' % t))))
    finally:
        s.close()


if __name__ == '__main__':
    main()
