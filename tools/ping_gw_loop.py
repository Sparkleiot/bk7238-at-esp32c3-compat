#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Ping the gateway repeatedly from the module, interleaved with PC->gateway pings,
to see whether the router simply never answers the module (or it is transient).
"""
import subprocess
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else 'COM5'
GW = sys.argv[2] if len(sys.argv) > 2 else '192.168.0.1'


def xchg(s, cmd, wait=3.2):
    s.reset_input_buffer()
    s.write((cmd + '\r\n').encode())
    time.sleep(wait)
    raw = s.read(1024)
    return [ln.strip() for ln in raw.decode('utf-8', 'replace').replace('\r', '').split('\n') if ln.strip()]


def pc_ping(ip, n=2):
    try:
        out = subprocess.run(['ping', '-n', str(n), '-w', '1000', ip],
                             capture_output=True, timeout=12).stdout
        return out.decode('gbk', 'replace').splitlines()[-1].strip()
    except Exception as e:
        return 'pc ping err %r' % (e,)


def main():
    s = serial.Serial(PORT, 115200, timeout=0.3)
    try:
        time.sleep(0.2)
        xchg(s, 'ATE0', 0.6)
        for i in range(4):
            m = xchg(s, 'AT+PING="%s"' % GW)
            print('  round%d  module -> %-14s %s' % (i + 1, GW, ' '.join(m)))
            print('          pc     -> %-14s %s' % (GW, pc_ping(GW)))
    finally:
        s.close()


if __name__ == '__main__':
    main()
