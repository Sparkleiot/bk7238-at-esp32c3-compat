#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""TCP-connect from the module to the gateway to prove L2/L3 bidirectionality.

If TCP to 192.168.0.1:80 CONNECTs, the module<->router path is fully working and
the gateway's ICMP non-reply is purely an ICMP policy on the router.
"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else 'COM5'


def xchg(s, cmd, wait=8.0):
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
        print('  reset links:', ' '.join(xchg(s, 'AT+CIPCLOSE=5', 1.5)))
        for cmd in ('AT+CIPMUX=1',
                    'AT+CIPSTART=0,"TCP","192.168.0.1",80',
                    'AT+CIPSTART=1,"TCP","192.168.0.1",53'):
            print('  %-40s -> %s' % (cmd, ' '.join(xchg(s, cmd))))
        print('  cleanup :', ' '.join(xchg(s, 'AT+CIPCLOSE=0', 1.5)))
        print('  cleanup :', ' '.join(xchg(s, 'AT+CIPCLOSE=1', 1.5)))
    finally:
        s.close()


if __name__ == '__main__':
    main()
