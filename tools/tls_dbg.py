#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Open the module log (ATE1) and capture everything around an AT+CIPSTART="TLS".

The HAL prints mbedtls error codes via bk_printf; ATE1 is the only way to see them.
"""
import os
import sys
import threading
import time

import serial

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from at_module_to_module_test import AT  # noqa: E402

COM = next((a for a in sys.argv[1:] if a.upper().startswith('COM')), 'COM5')
PCIP = sys.argv[sys.argv.index('--pc') + 1] if '--pc' in sys.argv else '192.168.0.152'
PORT = sys.argv[sys.argv.index('--port') + 1] if '--port' in sys.argv else '8443'


def main():
    a = AT('TLSDBG', COM, 'test/doc_v15_raw')
    os.makedirs('test/doc_v15_raw', exist_ok=True)
    try:
        # escape passthrough if stuck
        a.clear()
        a.send(line='AT')
        time.sleep(1.0)
        if 'OK' not in a.pump(1.0):
            a.clear()
            a.send(raw=b'\r\n')
            time.sleep(1.2)
            a.send(raw=b'+++')
            time.sleep(1.2)
        a.clear()
        a.send(line='ATE1')
        time.sleep(0.5)
        a.pump(0.5)
        for c in ('AT+CIPCLOSE', 'AT+CIPMODE=0', 'AT+CIPMUX=0'):
            a.clear()
            a.send(line=c)
            time.sleep(1.2)
            a.pump(0.5)

        print('=== AT+CIPSTART="TLS" (logs on) ===')
        a.clear()
        a.send(line='AT+CIPSTART="TLS","%s",%s' % (PCIP, PORT))
        t0 = time.time()
        buf = ''
        while time.time() - t0 < 25:
            buf += a.pump(0.3)
            if 'CONNECT' in buf or 'ERROR' in buf:
                time.sleep(1.5)
                buf += a.pump(0.5)
                break
        print(buf)
        print('=== end ===')

        a.clear()
        a.send(line='ATE0')
        time.sleep(0.5)
    finally:
        a.close()


if __name__ == '__main__':
    main()