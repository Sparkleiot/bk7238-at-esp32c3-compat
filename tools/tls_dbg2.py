#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Full TLS send-path debug: server thread + module logs (ATE1) in one file."""
import os
import re
import socket
import ssl
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from at_module_to_module_test import AT  # noqa: E402

COM = next((a for a in sys.argv[1:] if a.upper().startswith('COM')), 'COM5')
PCIP = '192.168.0.152'
PORT = 8446
CERT = os.path.join(HERE, '..', 'work', 'tls', 'cert.pem')
KEY = os.path.join(HERE, '..', 'work', 'tls', 'key.pem')


def srv():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers('ALL:@SECLEVEL=0')
    ctx.load_cert_chain(CERT, KEY)
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', PORT))
    s.listen(4)
    s.settimeout(1.0)
    print('[srv] listening %d' % PORT, flush=True)
    while True:
        try:
            raw, addr = s.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        threading.Thread(target=handler, args=(ctx, raw, addr), daemon=True).start()


def handler(ctx, raw, addr):
    try:
        raw.settimeout(20)
        c = ctx.wrap_socket(raw, server_side=True)
        print('[srv] handshake OK %s %s' % (c.version(), c.cipher()[0]), flush=True)
        while True:
            d = c.recv(2048)
            if not d:
                print('[srv] eof', flush=True)
                break
            print('[srv] RECV %dB %r -> echo' % (len(d), d[:40]), flush=True)
            c.sendall(d)
            print('[srv] echoed', flush=True)
    except Exception as e:
        print('[srv] err %s %r' % (type(e).__name__, e), flush=True)
    finally:
        for x in ('c', 'raw'):
            try:
                locals()[x].close()
            except Exception:
                pass


def main():
    threading.Thread(target=srv, daemon=True).start()
    time.sleep(0.8)
    a = AT('TLSDBG2', COM, 'test/doc_v15_raw')
    os.makedirs('test/doc_v15_raw', exist_ok=True)
    try:
        a.clear()
        a.send(line='AT')
        time.sleep(1.0)
        if 'OK' not in a.pump(1.0):
            a.clear()
            a.send(raw=b'\r\n')
            time.sleep(1.2)
            a.send(raw=b'+++')
            time.sleep(1.2)
        # 注意: 这里**不开** ATE1。ATE1 会把 mbedtls 的 bk_printf 日志灌满 UART1
        # (bk_printf 逐字节写且无锁), AT 应答会被日志淹没/交错, 反而什么都看不到。
        for c in ('ATE0', 'AT+CIPCLOSE', 'AT+CIPMODE=0', 'AT+CIPMUX=0'):
            a.clear()
            a.send(line=c)
            time.sleep(1.2)
            a.pump(0.4)
        a.clear()

        print('=== CIPSTART TLS ===', flush=True)
        a.send(line='AT+CIPSTART="TLS","%s",%d' % (PCIP, PORT))
        t0 = time.time()
        buf = ''
        while time.time() - t0 < 20:
            buf += a.pump(0.3)
            if 'CONNECT' in buf or 'ERROR' in buf:
                break
        time.sleep(1.0)
        buf += a.pump(0.5)
        print('--- after CIPSTART ---', flush=True)
        print(repr(buf[-600:]), flush=True)

        print('=== CIPSEND ===', flush=True)
        a.clear()
        a.send(line='AT+CIPSEND=10')
        t0 = time.time()
        buf = ''
        while time.time() - t0 < 6:
            buf += a.pump(0.2)
            if '>' in buf:
                break
        print('prompt buf: %r' % buf, flush=True)
        a.clear()
        a.send(raw=b'sparkleiot')
        t0 = time.time()
        buf = ''
        while time.time() - t0 < 10:
            buf += a.pump(0.3)
            if 'SEND OK' in buf or 'CLOSED' in buf or 'ERROR' in buf:
                break
        time.sleep(1.0)
        buf += a.pump(0.5)
        print('after send: %r' % buf[-600:], flush=True)

        print('=== waiting for +IPD echo ===', flush=True)
        a.clear()
        t0 = time.time()
        buf = ''
        while time.time() - t0 < 8:
            buf += a.pump(0.3)
        print('ipd: %r' % buf[-400:], flush=True)

        a.clear()
        a.send(line='ATE0')
        time.sleep(0.5)
    finally:
        a.close()


if __name__ == '__main__':
    main()