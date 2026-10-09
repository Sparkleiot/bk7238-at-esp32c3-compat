#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""AT+CIPSTART="TLS" 实测。

起一个本地 TLS 回显服务器(自签证书, 强制 TLS 1.2 —— 模组是 mbedtls 2.27, 不支持
TLS 1.3), 然后从模组发起 TLS 连接, 验证:
  1. AT+CIPSSLCCONF? / AT+CIPSSLCCONF=<n> 新命令可用
  2. AT+CIPSTART="TLS",<ip>,<port> 能 CONNECT   (修复前: 100% ERROR)
  3. AT+CIPSTART="SSL",... (ESP-AT 经典写法) 也能 CONNECT
  4. 双向收发: AT+CIPSEND -> 服务端回显 -> 模组 +IPD

用法: <python> tools/tls_probe.py [COM] [--port 8443] [--pc 192.168.0.152]
"""
import os
import re
import socket
import ssl
import sys
import threading
import time

import serial

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from at_module_to_module_test import AT  # noqa: E402

CERT = os.path.join(HERE, '..', 'work', 'tls', 'cert.pem')
KEY = os.path.join(HERE, '..', 'work', 'tls', 'key.pem')

ARGS = sys.argv[1:]
COM = next((a for a in ARGS if a.upper().startswith('COM')), 'COM5')
PORT = int(ARGS[ARGS.index('--port') + 1]) if '--port' in ARGS else 8443
PCIP = ARGS[ARGS.index('--pc') + 1] if '--pc' in ARGS else '192.168.0.152'

PAYLOAD = b'sparkleiot'
ECHO = 'SparkleIOT'.encode('utf-8')

results = []


def add(name, ok, detail=''):
    results.append((name, ok, detail))
    print('  [%s] %-46s %s' % ('PASS' if ok else 'FAIL', name, detail))


# ---------------------------------------------------------------- TLS server
def tls_server():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    # 关键: 模组的 mbedtls 只报**静态 RSA** 套件(实测 ClientHello 只有
    # TLS_RSA_WITH_AES_*, 零 ECDHE), 而 OpenSSL 3.x 的默认 cipher 串刻意
    # 排除了无前向保密的 RSA-kex => NO_SHARED_CIPHER。
    # 放宽服务端到 SECLEVEL=0 才能和它对上。
    try:
        ctx.set_ciphers('ALL:@SECLEVEL=0')
    except Exception as e:
        print('  [server] set_ciphers failed: %r' % (e,))
    ctx.load_cert_chain(CERT, KEY)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', PORT))
    srv.listen(4)
    srv.settimeout(1.0)
    print('  [server] TLS1.2 echo listening on :%d' % PORT)
    while True:
        try:
            raw, addr = srv.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        threading.Thread(target=handle, args=(ctx, raw, addr), daemon=True).start()


def handle(ctx, raw, addr):
    try:
        raw.settimeout(12)
        c = ctx.wrap_socket(raw, server_side=True)
        print('  [server] handshake OK from %s:%d  tls=%s cipher=%s'
              % (addr[0], addr[1], c.version(), c.cipher()[0]))
        while True:
            d = c.recv(2048)
            if not d:
                break
            print('  [server] recv %dB %r -> echo' % (len(d), d[:40]))
            c.sendall(d)
    except Exception as e:
        print('  [server] %s: %r' % (type(e).__name__, e))
    finally:
        try:
            c.close()
        except Exception:
            pass
        try:
            raw.close()
        except Exception:
            pass


# ---------------------------------------------------------------- AT helpers
def cmd(a, line, t=12):
    a.clear()
    a.send(line=line)
    t0 = time.time()
    acc = ''
    while time.time() - t0 < t:
        acc += a.pump(0.2)
        if re.search(r'\r?\nOK\r?\n', acc) or 'ERROR' in acc:
            break
    return acc


def main():
    threading.Thread(target=tls_server, daemon=True).start()
    time.sleep(0.8)

    a = AT('TLSPROBE', COM, 'test/doc_v15_raw')
    os.makedirs('test/doc_v15_raw', exist_ok=True)
    try:
        # 脱离可能残留的透传态(否则所有 AT 都被吞掉)
        a.clear()
        a.send(line='AT')
        time.sleep(1.0)
        acc = a.pump(1.0)
        if 'OK' not in acc:
            a.clear()
            a.send(raw=b'\r\n')
            time.sleep(1.2)
            a.send(raw=b'+++')
            time.sleep(1.2)
            a.clear()
            a.send(line='AT')
            time.sleep(1.0)
            a.pump(1.0)
        cmd(a, 'ATE0', 3)

        # --- 1. AT+CIPSSLCCONF
        acc = cmd(a, 'AT+CIPSSLCCONF?', 5)
        add('AT+CIPSSLCCONF? 查询', '+CIPSSLCCONF:' in acc and 'OK' in acc,
            ' | '.join(l.strip() for l in acc.replace('\r', '').split('\n') if l.strip())[:80])

        acc = cmd(a, 'AT+CIPSSLCCONF=2,0,0', 5)
        acc2 = cmd(a, 'AT+CIPSSLCCONF=0', 5)
        acc3 = cmd(a, 'AT+CIPSSLCCONF?', 5)
        add('AT+CIPSSLCCONF=<n> 设置/校验模式0',
            'ERROR' not in acc and 'ERROR' not in acc2 and '+CIPSSLCCONF:0' in acc3,
            acc3.replace('\r', ' ').strip()[:70])

        cmd(a, 'AT+CIPMUX=0', 4)
        cmd(a, 'AT+CIPCLOSE', 4)

        # --- 2. TLS
        acc = cmd(a, 'AT+CIPSTART="TLS","%s",%d' % (PCIP, PORT), 20)
        ok_tls = 'CONNECT' in acc and 'ERROR' not in acc
        add('AT+CIPSTART="TLS" CONNECT', ok_tls,
            acc.replace('\r', ' ').strip()[:90])

        if ok_tls:
            n = len(PAYLOAD)
            a.clear()
            a.send(line='AT+CIPSEND=%d' % n)
            t0 = time.time()
            buf = ''
            while time.time() - t0 < 5 and '>' not in buf:
                buf += a.pump(0.2)
            a.clear()
            a.send(raw=PAYLOAD)
            t0 = time.time()
            acc_all = ''
            while time.time() - t0 < 10:
                acc_all += a.pump(0.3)
                # SEND OK 说明模组已发出; +IPD 说明回显回来了
                if 'SEND OK' in acc_all and PAYLOAD.decode() in acc_all:
                    break
            add('TLS 双向: CIPSEND + 回显 +IPD',
                ('SEND OK' in acc_all) and (PAYLOAD.decode() in acc_all),
                acc_all.replace('\r', ' ').strip()[:100])
            cmd(a, 'AT+CIPCLOSE', 5)

        # --- 3. "SSL" alias
        acc = cmd(a, 'AT+CIPSTART="SSL","%s",%d' % (PCIP, PORT), 20)
        ok_ssl = 'CONNECT' in acc and 'ERROR' not in acc
        add('AT+CIPSTART="SSL" (ESP-AT 经典写法)', ok_ssl,
            acc.replace('\r', ' ').strip()[:90])
        if ok_ssl:
            cmd(a, 'AT+CIPCLOSE', 5)

        cmd(a, 'AT+CIPMODE=0', 4)
        cmd(a, 'AT+CIPCLOSE', 4)
    finally:
        a.close()

    npass = sum(1 for _, ok, _ in results if ok)
    print('\n[tls_probe] %d PASS / %d FAIL' % (npass, len(results) - npass))


if __name__ == '__main__':
    main()