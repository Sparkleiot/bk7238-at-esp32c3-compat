#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
本机网络调试助手（自研，替代串口/网络调试工具）—— 供 BK7238 / XH-WB3S 模组联网联调使用。

同时提供三个服务：
    TCP  0.0.0.0:8266   连接即下发问候语; 收到数据后回 "ECHO:<原内容>"
    UDP  0.0.0.0:8267   收到数据报后原样回 "UDP-ECHO:<原内容>"
    HTTP 0.0.0.0:8080   任意 GET 返回一小段 JSON (供 AT+HTTPCLIENT 测试)

用法:
    python net_debug_server.py                       # 默认端口
    python net_debug_server.py --seconds 120         # 跑 120 秒后自动退出
    python net_debug_server.py --tcp-port 9000
日志同时打印到 stdout 与 work/net_server.log。
"""
import argparse
import json
import os
import socket
import sys
import threading
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG_PATH = os.path.join(ROOT, 'work', 'net_server.log')

_lock = threading.Lock()
_fh = None


def log(msg):
    line = '[%s] %s' % (datetime.now().strftime('%H:%M:%S.%f')[:-3], msg)
    with _lock:
        print(line, flush=True)
        if _fh:
            _fh.write(line + '\n')
            _fh.flush()


def preview(data: bytes, limit: int = 96) -> str:
    s = data[:limit].decode('utf-8', 'replace').replace('\r', '\\r').replace('\n', '\\n')
    if len(data) > limit:
        s += '...(+%dB)' % (len(data) - limit)
    return s


# ---------------------------------------------------------------------------
# TCP 服务
# ---------------------------------------------------------------------------
def tcp_server(port, stop_evt):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', port))
    srv.listen(4)
    srv.settimeout(0.5)
    log('TCP  listening 0.0.0.0:%d' % port)

    while not stop_evt.is_set():
        try:
            conn, addr = srv.accept()
        except socket.timeout:
            continue
        except OSError as e:
            log('TCP  accept error: %s' % e)
            break
        log('TCP  +CONNECT from %s:%d' % (addr[0], addr[1]))
        threading.Thread(target=tcp_session, args=(conn, addr), daemon=True).start()

    srv.close()
    log('TCP  closed')


def tcp_session(conn, addr):
    conn.settimeout(0.5)
    greeting = b'HELLO-FROM-PC\r\n'
    try:
        conn.sendall(greeting)
        log('TCP  ->  %s' % preview(greeting))
    except OSError:
        pass

    buf = b''
    try:
        while True:
            try:
                data = conn.recv(4096)
            except socket.timeout:
                continue
            except OSError as e:
                log('TCP  recv error from %s: %s' % (addr[0], e))
                break
            if not data:
                break
            log('TCP  <-  %s' % preview(data))
            buf += data
            # 收到 PUSH:xxx 时主动下发 xxx，其余情况回显
            reply = None
            text = buf.decode('utf-8', 'replace')
            if text.startswith('PUSH:'):
                reply = text[5:].strip().encode() + b'\r\n'
                buf = b''
            elif b'\n' in buf or b'\r' in buf:
                reply = b'ECHO:' + buf.rstrip(b'\r\n') + b'\r\n'
                buf = b''
            if reply:
                try:
                    conn.sendall(reply)
                    log('TCP  ->  %s' % preview(reply))
                except OSError as e:
                    log('TCP  send error: %s' % e)
                    break
    finally:
        conn.close()
        log('TCP  -DISCONNECT %s:%d' % (addr[0], addr[1]))


# ---------------------------------------------------------------------------
# UDP 服务
# ---------------------------------------------------------------------------
def udp_server(port, stop_evt):
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', port))
    srv.settimeout(0.5)
    log('UDP  listening 0.0.0.0:%d' % port)

    while not stop_evt.is_set():
        try:
            data, addr = srv.recvfrom(4096)
        except socket.timeout:
            continue
        except OSError as e:
            log('UDP  recv error: %s' % e)
            break
        log('UDP  <-  %s:%d  %s' % (addr[0], addr[1], preview(data)))
        try:
            srv.sendto(b'UDP-ECHO:' + data, addr)
            log('UDP  ->  %s:%d  UDP-ECHO:%s' % (addr[0], addr[1], preview(data)))
        except OSError as e:
            log('UDP  send error: %s' % e)

    srv.close()
    log('UDP  closed')


# ---------------------------------------------------------------------------
# HTTP 服务（供 AT+HTTPCLIENT 使用）
# ---------------------------------------------------------------------------
def http_server(port, stop_evt):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', port))
    srv.listen(4)
    srv.settimeout(0.5)
    log('HTTP listening 0.0.0.0:%d' % port)

    while not stop_evt.is_set():
        try:
            conn, addr = srv.accept()
        except socket.timeout:
            continue
        except OSError as e:
            log('HTTP accept error: %s' % e)
            break
        conn.settimeout(2.0)
        try:
            req = conn.recv(2048)
            log('HTTP <-  %s:%d  %s' % (addr[0], addr[1], preview(req)))
            body = json.dumps({
                "device": "BK7238",
                "module": "XH-WB3S",
                "at": "esp32c3-compat",
                "from": "net_debug_server",
                "ts": int(time.time()),
            }, separators=(',', ':')).encode()
            head = (
                'HTTP/1.1 200 OK\r\n'
                'Content-Type: application/json\r\n'
                'Content-Length: %d\r\n'
                'Connection: close\r\n'
                '\r\n' % len(body)
            ).encode()
            conn.sendall(head + body)
            log('HTTP ->  %s:%d  %dB json' % (addr[0], addr[1], len(body)))
        except OSError as e:
            log('HTTP error: %s' % e)
        finally:
            conn.close()

    srv.close()
    log('HTTP closed')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tcp-port', type=int, default=8266)
    ap.add_argument('--udp-port', type=int, default=8267)
    ap.add_argument('--http-port', type=int, default=8080)
    ap.add_argument('--seconds', type=float, default=0.0, help='0 = 一直运行')
    args = ap.parse_args()

    global _fh
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    _fh = open(LOG_PATH, 'w', encoding='utf-8')
    log('=== net_debug_server started (tcp=%d udp=%d http=%d) ==='
        % (args.tcp_port, args.udp_port, args.http_port))

    stop_evt = threading.Event()
    threads = [
        threading.Thread(target=tcp_server, args=(args.tcp_port, stop_evt), daemon=True),
        threading.Thread(target=udp_server, args=(args.udp_port, stop_evt), daemon=True),
        threading.Thread(target=http_server, args=(args.http_port, stop_evt), daemon=True),
    ]
    for t in threads:
        t.start()

    try:
        if args.seconds > 0:
            time.sleep(args.seconds)
            stop_evt.set()
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        stop_evt.set()
    for t in threads:
        t.join(timeout=2)
    log('=== stopped ===')
    if _fh:
        _fh.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
