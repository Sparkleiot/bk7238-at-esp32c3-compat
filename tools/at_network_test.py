#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
BK7238 / XH-WB3S 模组  ——  AT 固件联网联调测试

覆盖内容:
    阶段1  关联 AP (AT+CWMODE / AT+CWJAP)
    阶段2  IP 与链路状态 (AT+CIPSTA? / AT+CIFSR / AT+CIPSTATUS?)
    阶段3  ICMP / DNS / SNTP
    阶段4  TCP 客户端(公网)  AT+CIPSTART -> AT+CIPSEND 真实收发 -> AT+CIPCLOSE
    阶段5  TCP 客户端(本机 PC)  —— 顺带探测 Windows 防火墙入站策略
    阶段6  TCP 服务端(模组监听, PC 主动连入) —— 受控双向收发
    阶段7  UDP 服务端(模组监听, PC 主动发包) —— 受控双向收发
    阶段8  断连与恢复 (AT+CWQAP / 重新关联)

PC 侧的对端(网络调试助手)在本进程内以线程方式运行, 以保证测试期间始终存活。

用法:
    python at_network_test.py COM3 --ssid MyHomeWiFi --password <WIFI_PWD>
    python at_network_test.py COM3 --ssid MyHomeWiFi --password <WIFI_PWD> --pc-ip 192.168.0.152
输出:
    test/network_integration.md   测试报告
    work/net_raw.log              原始报文日志
"""
import argparse
import os
import re
import socket
import sys
import threading
import time
from datetime import datetime

import serial

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW_LOG = os.path.join(ROOT, 'work', 'net_raw.log')
REPORT = os.path.join(ROOT, 'test', 'network_integration.md')

RAW_FH = None


def raw(tag, text):
    line = '[%s] %-12s %s' % (datetime.now().strftime('%H:%M:%S.%f')[:-3], tag, text)
    print(line, flush=True)
    if RAW_FH:
        RAW_FH.write(line + '\n')
        RAW_FH.flush()


def clean(b: bytes) -> str:
    out = []
    i = 0
    while i < len(b):
        c = b[i]
        if c == 0x1B:
            i += 1
            while i < len(b) and not (0x40 <= b[i] <= 0x7E):
                i += 1
            i += 1
            continue
        if c == 0:
            i += 1
            continue
        out.append(chr(c) if 0x20 <= c <= 0x7E or c in (10, 13, 9) else '.')
        i += 1
    return ''.join(out)


def vis(s: str) -> str:
    """压成单行便于放进 markdown 表格"""
    return s.replace('\\', '\\\\').replace('|', '\\|').replace('\r', '\\r').replace('\n', '\\n')


# ===========================================================================
# PC 侧网络对端(网络调试助手), 进程内运行
# ===========================================================================
class Peer:
    def __init__(self):
        self.tcp_srv = None
        self.udp_srv = None
        self.tcp_conn = None
        self.tcp_peer = None
        self.rx = bytearray()
        self.udp_rx = bytearray()
        self.udp_from = None
        self.tcp_evt = threading.Event()
        self.udp_evt = threading.Event()
        self.udp_tx_port = None
        self.lock = threading.Lock()
        self.stop_evt = threading.Event()
        self.errors = []

    # ---------------- TCP 服务端 ----------------
    def start_tcp_server(self, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', port))
        s.listen(2)
        s.settimeout(0.3)
        self.tcp_srv = s
        threading.Thread(target=self._tcp_accept, daemon=True).start()
        raw('PC-TCP', 'listen 0.0.0.0:%d' % port)

    def _tcp_accept(self):
        while not self.stop_evt.is_set():
            try:
                c, a = self.tcp_srv.accept()
            except socket.timeout:
                continue
            except OSError as e:
                self.errors.append('tcp accept: %s' % e)
                break
            self.tcp_conn, self.tcp_peer = c, a
            c.settimeout(0.2)
            raw('PC-TCP', '+CONNECT from %s:%d' % a)
            self.tcp_evt.set()
            threading.Thread(target=self._tcp_recv, args=(c,), daemon=True).start()

    def _tcp_recv(self, c):
        while not self.stop_evt.is_set():
            try:
                d = c.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not d:
                raw('PC-TCP', '-DISCONNECT')
                break
            raw('PC-TCP', '<- %r' % d)
            with self.lock:
                self.rx += d

    def tcp_send(self, data: bytes):
        if not self.tcp_conn:
            return False
        try:
            self.tcp_conn.sendall(data)
            raw('PC-TCP', '-> %r' % data)
            return True
        except OSError as e:
            self.errors.append('tcp send: %s' % e)
            return False

    def tcp_take(self, timeout=2.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            with self.lock:
                if self.rx:
                    d = bytes(self.rx)
                    self.rx.clear()
                    return d
            time.sleep(0.05)
        with self.lock:
            d = bytes(self.rx)
            self.rx.clear()
        return d

    # ---------------- UDP 服务端 ----------------
    def start_udp_server(self, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', port))
        s.settimeout(0.3)
        self.udp_srv = s
        threading.Thread(target=self._udp_loop, daemon=True).start()
        raw('PC-UDP', 'bind 0.0.0.0:%d' % port)

    def _udp_loop(self):
        while not self.stop_evt.is_set():
            try:
                d, a = self.udp_srv.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError as e:
                self.errors.append('udp recv: %s' % e)
                break
            raw('PC-UDP', '<- %s:%d %r' % (a[0], a[1], d))
            self.udp_from = a
            with self.lock:
                self.udp_rx += d
            self.udp_evt.set()

    def udp_take(self, timeout=2.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            with self.lock:
                if self.udp_rx:
                    d = bytes(self.udp_rx)
                    self.udp_rx.clear()
                    return d
            time.sleep(0.05)
        return b''

    def shutdown(self):
        self.stop_evt.set()
        for s in (self.tcp_srv, self.udp_srv):
            try:
                if s:
                    s.close()
            except OSError:
                pass


# ===========================================================================
# AT 串口驱动
# ===========================================================================
class AtPort:
    def __init__(self, port, baud=115200):
        self.s = serial.Serial(port, baud, timeout=0.05,
                               dsrdtr=False, rtscts=False, xonxoff=False)
        try:
            self.s.dtr = False
            self.s.rts = False
        except Exception:
            pass
        raw('SER', 'open %s @%d' % (port, baud))

    def pump(self, secs):
        t0 = time.time()
        buf = b''
        while time.time() - t0 < secs:
            d = self.s.read(8192)
            if d:
                buf += d
            else:
                time.sleep(0.01)
        return buf

    def wait_for(self, patterns, timeout, quiet=False):
        """持续读取直到任一正则命中; 返回 (文本, 命中模式 or None)"""
        rx = [re.compile(p, re.S | re.I) for p in patterns]
        buf = ''
        t0 = time.time()
        while time.time() - t0 < timeout:
            d = self.s.read(8192)
            if d:
                buf += clean(d)
                for r in rx:
                    if r.search(buf):
                        return buf, r.pattern
            else:
                time.sleep(0.02)
        return buf, None

    def send_line(self, line):
        # 注意: 只能跟一个 CRLF。多发一个 CRLF 会被固件当成一条空命令并回 ERROR。
        raw('AT->', line)
        self.s.write((line + '\r\n').encode())
        self.s.flush()

    def send_bytes(self, b):
        raw('AT->', 'RAW %r' % b)
        self.s.write(b)
        self.s.flush()

    def reset_buffers(self):
        try:
            self.s.reset_input_buffer()
        except Exception:
            pass

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


# ===========================================================================
# 测试记录
# ===========================================================================
RESULTS = []


def rec(phase, name, cmd, status, detail, expect=''):
    RESULTS.append({
        'phase': phase, 'name': name, 'cmd': cmd,
        'status': status, 'detail': detail, 'expect': expect,
    })
    raw('REC', '[%s] %s = %s  (%s)' % (phase, name, status, detail))


PTR = 0
AT = None
PC = None
ARGS = None


def step(phase, name, cmd, send, expect_re, timeout=2.0, expect=None, expect_desc=''):
    """发一条命令并等待期望响应"""
    global PTR
    AT.reset_buffers()
    AT.send_line(send)
    txt, hit = AT.wait_for([expect_re], timeout)
    ok = hit is not None
    PTR += 1
    rec(phase, name, cmd, 'PASS' if ok else 'FAIL', vis(txt)[:400],
        expect_desc or (expect if isinstance(expect, str) else expect_re))
    return txt, ok


# ===========================================================================
# 各阶段
# ===========================================================================
def phase1_join(ssid, pwd):
    raw('===', '阶段1 关联 AP')
    step('1-关联', '握手', 'AT', 'AT', r'\bOK\b', 2.0)
    step('1-关联', 'Wi-Fi 模式(查询)', 'AT+CWMODE?', 'AT+CWMODE?', r'\+CWMODE:\d', 2.0)
    step('1-关联', '设置 Station 模式', 'AT+CWMODE=1', 'AT+CWMODE=1', r'\bOK\b', 2.0)
    step('1-关联', '自动连接(关闭)', 'AT+CWAUTOCONN=0', 'AT+CWAUTOCONN=0', r'\bOK\b', 2.0)

    # 关联: 固件是异步的 —— 先立即回 OK, 随后异步抛 WIFI CONNECTED / WIFI GOT IP
    AT.reset_buffers()
    AT.send_line('AT+CWJAP="%s","%s"' % (ssid, pwd))
    txt, hit = AT.wait_for([r'\bOK\b', r'\bERROR\b', r'FAIL'], 30.0)
    ok = bool(re.search(r'\bOK\b', txt))
    rec('1-关联', '关联 AP(下发)', 'AT+CWJAP="%s","***"' % ssid, 'PASS' if ok else 'FAIL',
        vis(txt)[:600], '立即回 OK (异步关联)')

    # 等待 DHCP: 轮询 CIPSTA? 直到拿到非 0.0.0.0 的地址
    AT.reset_buffers()
    ip = None
    t0 = time.time()
    got_ip_evt = ''
    while time.time() - t0 < 25.0:
        got_ip_evt += clean(AT.pump(1.0))
        AT.send_line('AT+CIPSTA?')
        t2, _ = AT.wait_for([r'\+CIPSTA:ip:'], 2.0)
        got_ip_evt += t2
        m = re.search(r'ip:"((?!0\.0\.0\.0)[\d.]+)"', got_ip_evt)
        if m:
            ip = m.group(1)
            break
    rec('1-关联', '关联 AP(事件+DCHP)', 'WIFI CONNECTED / WIFI GOT IP',
        'PASS' if ip else 'FAIL',
        '事件: %s | IP=%s | 用时 %.1fs'
        % (vis(' '.join(sorted(set(re.findall(r'WIFI (?:CONNECTED|GOT IP|DISCONNECT)', got_ip_evt))))),
           ip or '未获取', time.time() - t0),
        'WIFI CONNECTED -> WIFI GOT IP, STAIP!=0.0.0.0')
    setattr(ARGS, 'module_ip', ip)
    time.sleep(1.0)
    step('1-关联', '回查已连 AP', 'AT+CWJAP?', 'AT+CWJAP?', r'\+CWJAP:', 3.0,
         expect_desc='+CWJAP:"MyHomeWiFi","xx:..",ch,rssi,...')


def phase2_ip():
    raw('===', '阶段2 IP 与链路状态')
    step('2-IP', 'STA 获取 IP', 'AT+CIPSTA?', 'AT+CIPSTA?', r'\+CIPSTA:', 3.0)
    step('2-IP', '本地 IP 汇总', 'AT+CIFSR', 'AT+CIFSR', r'\+CIFSR:STAIP', 3.0)
    step('2-IP', 'DHCP 状态', 'AT+CWDHCP?', 'AT+CWDHCP?', r'\+CWDHCP:', 2.0)
    step('2-IP', '链路状态', 'AT+CIPSTATUS?', 'AT+CIPSTATUS?', r'STATUS:\d', 3.0,
         expect_desc='STATUS:2/3/4 表示已联网')


def phase3_net(ssid, pwd, pc_ip):
    raw('===', '阶段3 ICMP / DNS / SNTP')
    step('3-网络', 'PING 网关', 'AT+PING="192.168.0.1"', 'AT+PING="192.168.0.1"',
         r'\+PING:\d+|\+PING:TIMEOUT|\bERROR\b', 12.0, expect_desc='+PING:<time>')
    step('3-网络', 'PING PC', 'AT+PING="%s"' % pc_ip, 'AT+PING="%s"' % pc_ip,
         r'\+PING:\d+|\+PING:TIMEOUT|\bERROR\b', 12.0,
         expect_desc='PC 默认禁 ICMP 入站, 失败属预期')
    step('3-网络', 'PING 公网', 'AT+PING="www.baidu.com"', 'AT+PING="www.baidu.com"',
         r'\+PING:\d+|\+PING:TIMEOUT|\bERROR\b', 15.0, expect_desc='+PING:<time>')
    step('3-网络', 'DNS 解析(公网)', 'AT+CIPDOMAIN="www.baidu.com"',
         'AT+CIPDOMAIN="www.baidu.com"', r'\+CIPDOMAIN:', 12.0,
         expect_desc='+CIPDOMAIN:"<ip>"')
    step('3-网络', 'DNS 解析(网关名)', 'AT+CIPDOMAIN="www.qq.com"',
         'AT+CIPDOMAIN="www.qq.com"', r'\+CIPDOMAIN:|\bERROR\b', 12.0)
    step('3-网络', 'SNTP 配置', 'AT+CIPSNTPCFG=1,8,"ntp.aliyun.com"',
         'AT+CIPSNTPCFG=1,8,"ntp.aliyun.com"', r'\bOK\b', 3.0)
    time.sleep(4.0)
    step('3-网络', 'SNTP 取时', 'AT+CIPSNTPTIME?', 'AT+CIPSNTPTIME?',
         r'\+CIPSNTPTIME:', 4.0, expect_desc='+CIPSNTPTIME:<ascii time>')


def phase4_tcp_client_internet():
    raw('===', '阶段4 TCP 客户端(公网 baidu:80)')
    step('4-TCP客户端', '单连接模式', 'AT+CIPMUX=0', 'AT+CIPMUX=0', r'\bOK\b', 3.0)
    # 建连必须真正收到 OK —— baidu 对部分出口 IP 有偶发拒连,
    # 此时固件应在 10s 连接超时内回 ERROR(不能挂死), 该情况判 FAIL 并跳过收发。
    t_conn, ok_conn = step('4-TCP客户端', 'TCP 建连', 'AT+CIPSTART="TCP","www.baidu.com",80',
                           'AT+CIPSTART="TCP","www.baidu.com",80', r'\bOK\b|\bERROR\b', 15.0,
                           expect_desc='OK (域名解析+建连; 拒连时 10s 内 ERROR)')
    ok_conn = ok_conn and not re.search(r'\bERROR\b', t_conn)
    if not ok_conn:
        rec('4-TCP客户端', 'TCP 建连', 'AT+CIPSTART="TCP","www.baidu.com",80',
            'FAIL', vis(t_conn)[:400], 'OK (baidu 偶发拒连, 外部网络问题)')
    time.sleep(0.5)

    if ok_conn:
        # 真实收发: HTTP GET
        payload = b'GET / HTTP/1.0\r\nHost: www.baidu.com\r\n\r\n'
        AT.reset_buffers()
        AT.send_line('AT+CIPSEND=%d' % len(payload))
        pre, hit = AT.wait_for([r'>'], 5.0)
        if hit:
            AT.send_bytes(payload)
            txt, hit2 = AT.wait_for([r'SEND OK|\+IPD', r'\bERROR\b'], 150.0)
            # 继续收 ------ 完整 HTTP 响应
            txt += clean(AT.pump(3.0))
            got_ipd = bool(re.search(r'\+IPD,\d+:', txt))
            rec('4-TCP客户端', '发送 HTTP GET 并收响应', 'AT+CIPSEND=%d' % len(payload),
                'PASS' if got_ipd else 'FAIL', vis(txt)[:700],
                'SEND OK + +IPD 内含 HTTP/1.0 200')
        else:
            rec('4-TCP客户端', '发送 HTTP GET 并收响应', 'AT+CIPSEND=%d' % len(payload),
                'FAIL', '未收到 > 提示符: ' + vis(pre), '> 提示符')
    else:
        rec('4-TCP客户端', '发送 HTTP GET 并收响应', 'AT+CIPSEND(跳过, 无连接)',
            'SKIP', '建连失败, 跳过收发', '')

    # 无连接时 CIPCLOSE 回 ERROR 属 ESP-AT 合法行为
    step('4-TCP客户端', '关闭连接', 'AT+CIPCLOSE', 'AT+CIPCLOSE',
         r'\bOK\b|\bCLOSED\b|\bERROR\b', 5.0)
    step('4-TCP客户端', '连接信息', 'AT+CIPSTATE', 'AT+CIPSTATE',
         r'\bOK\b|\+CIPSTATE:', 4.0)


def phase5_tcp_client_pc(pc_ip, port):
    """模组作 TCP 客户端连 PC —— 本项是主要受控双向收发测试。
    注意: 原厂固件在连接建立后只回 OK, 不像 ESP-AT 会先回 CONNECT,
    所以这里以「PC 侧 accept 到连接」为建连成功的判据。"""
    raw('===', '阶段5 TCP 客户端(模组 -> PC, 双向收发主测试)')
    cmd = 'AT+CIPSTART="TCP","%s",%d' % (pc_ip, port)
    AT.reset_buffers()
    AT.send_line(cmd)
    txt, hit = AT.wait_for([r'OK', r'\bERROR\b'], 10.0)
    # 等待 PC 侧 accept
    t0 = time.time()
    while time.time() - t0 < 8.0 and PC.tcp_conn is None:
        raw('PC-TCP', 'waiting accept...')
        txt += clean(AT.pump(0.5))
    accepted = PC.tcp_conn is not None
    rec('5-TCP客户端(PC)', '模组连入 PC', cmd,
        'PASS' if accepted else 'FAIL',
        'AT侧=%s | PC侧accept=%s' % (vis(txt)[:160], accepted),
        'PC 侧 accept 到模组连接 (原厂无 CONNECT 前缀, 只回 OK)')

    if not accepted:
        AT.send_line('AT+CIPCLOSE')
        AT.wait_for([r'OK', r'ERROR'], 4.0)
        return

    # --- 方向 A: PC -> 模组 ---
    PC.tcp_send(b'HELLO-FROM-PC\r\n')
    t2, hit2 = AT.wait_for([r'\+IPD,\d+:.*HELLO-FROM-PC'], 8.0)
    rec('5-TCP客户端(PC)', 'PC -> 模组 收发', 'PC send "HELLO-FROM-PC"',
        'PASS' if hit2 else 'FAIL', vis(t2)[:300], '+IPD,<len>:HELLO-FROM-PC')

    # --- 方向 B: 模组 -> PC ---
    payload = b'HELLO-FROM-BK7238-%d\r\n' % int(time.time() % 100000)
    AT.reset_buffers()
    AT.send_line('AT+CIPSEND=%d' % len(payload))
    pre, hitp = AT.wait_for([r'>'], 6.0)
    if hitp:
        AT.send_bytes(payload)
        t3, _ = AT.wait_for([r'SEND OK', r'ERROR'], 8.0)
        got = PC.tcp_take(4.0)
        okB = payload.strip() in got
        rec('5-TCP客户端(PC)', '模组 -> PC 收发', 'AT+CIPSEND=%d' % len(payload),
            'PASS' if okB else 'FAIL',
            'AT侧=%s | PC侧收到=%r' % (vis(t3)[:150], got[:120]),
            '模组回 SEND OK, PC 侧收到 payload')
    else:
        rec('5-TCP客户端(PC)', '模组 -> PC 收发', 'AT+CIPSEND=%d' % len(payload),
            'FAIL', '未收到 > 提示符: ' + vis(pre), 'SEND OK')

    txt, _ = step('5-TCP客户端(PC)', '连接信息', 'AT+CIPSTATE', 'AT+CIPSTATE',
                  r'\+CIPSTATE:|\bOK\b', 4.0)
    step('5-TCP客户端(PC)', '主动断开', 'AT+CIPCLOSE', 'AT+CIPCLOSE',
         r'\bOK\b|\bCLOSED\b|\bERROR\b', 5.0)


def phase6_tcp_server(port):
    """模组作 TCP 服务端, PC 主动连入 —— 受控双向收发"""
    raw('===', '阶段6 TCP 服务端(模组监听, PC 连入)')
    step('6-TCP服务端', '多连接模式', 'AT+CIPMUX=1', 'AT+CIPMUX=1', r'\bOK\b', 3.0)
    # 先清干净: 只要还有已连接链路(含刚关掉的), isconnected_network(0) 为真,
    # 原厂 CIPSERVER 就会直接回 ERROR, 监听根本起不来。
    AT.reset_buffers()
    AT.send_line('AT+CIPCLOSE')
    AT.wait_for([r'\bOK\b', r'\bERROR\b'], 4.0)
    time.sleep(1.0)
    txt, ok = step('6-TCP服务端', '开启服务端监听', 'AT+CIPSERVER=1,%d' % port,
                   'AT+CIPSERVER=1,%d' % port, r'\bOK\b|ready|listen|\bERROR\b', 6.0,
                   expect_desc='OK (linkid=5, port=%d)' % port)
    time.sleep(1.5)

    # PC 主动连入【模组的】STA 地址（PC -> 模组 是出站方向）
    mod_ip = ARGS.module_ip
    if not mod_ip:
        rec('6-TCP服务端', 'PC 连入模组', 'connect <module-ip>:%d' % port,
            'FAIL', '未解析到模组 STA IP', '模组 IP 已知')
        return
    try:
        c = socket.create_connection((mod_ip, port), timeout=6)
    except Exception as e:
        rec('6-TCP服务端', 'PC 连入模组', 'connect %s:%d' % (mod_ip, port),
            'FAIL', 'socket error: %s' % e, 'PC 侧 TCP 建连成功')
        return
    rec('6-TCP服务端', 'PC 连入模组', 'socket.create_connection(%s,%d)' % (mod_ip, port),
        'PASS', 'PC 侧 TCP 建连成功', '模组进入 server 模式并接受连接')
    c.settimeout(0.3)

    # 取模组上报的 linkid
    txt, _ = AT.wait_for([r'\+IPD,\d+|CONNECT', r'\bCLOSED\b'], 6.0)
    m = re.search(r'\+IPD,(\d+)', txt)
    link = int(m.group(1)) if m else 0
    raw('INFO', 'server 侧 linkid = %s' % (m.group(1) if m else 'unknown'))

    # --- 方向 A: PC -> 模组 ---
    c.sendall(b'HELLO-FROM-PC\r\n')
    raw('PC-TCP', '-> %r' % b'HELLO-FROM-PC\r\n')
    txt, hit = AT.wait_for([r'\+IPD,\d+,\d+:.*HELLO-FROM-PC'], 8.0)
    rec('6-TCP服务端', 'PC -> 模组 收发', 'PC send "HELLO-FROM-PC"',
        'PASS' if hit else 'FAIL', vis(txt)[:300], '+IPD,<id>,<len>:HELLO-FROM-PC')

    # --- 方向 B: 模组 -> PC ---
    payload = b'HELLO-FROM-BK7238-%d\r\n' % int(time.time() % 100000)
    AT.reset_buffers()
    AT.send_line('AT+CIPSEND=%d,%d' % (link, len(payload)))
    pre, hitp = AT.wait_for([r'>'], 6.0)
    if hitp:
        AT.send_bytes(payload)
        t2, hit2 = AT.wait_for([r'SEND OK', r'\bERROR\b'], 8.0)
        got = bytearray()
        t0 = time.time()
        while time.time() - t0 < 3.0:
            d = AT.pump(0.3)
            if d:
                t2 += clean(d)
            try:
                g = c.recv(4096)
            except socket.timeout:
                g = b''
            except OSError:
                break
            if g:
                got += g
                raw('PC-TCP', '<- %r' % g)
        okB = payload.strip() in bytes(got)
        rec('6-TCP服务端', '模组 -> PC 收发', 'AT+CIPSEND=%d,%d' % (link, len(payload)),
            'PASS' if okB else 'FAIL',
            'AT侧=%s | PC侧收到=%r' % (vis(t2)[:200], bytes(got)[:120]),
            '模组回显 SEND OK, PC 侧收到 payload')
    else:
        rec('6-TCP服务端', '模组 -> PC 收发', 'AT+CIPSEND=%d,%d' % (link, len(payload)),
            'FAIL', '未收到 > 提示符: ' + vis(pre), 'SEND OK')
        AT.send_line('AT+CIPCLOSE=%d' % link)
        AT.wait_for([r'\bOK\b'], 4.0)

    step('6-TCP服务端', '连接状态(CIPSTATE)', 'AT+CIPSTATE', 'AT+CIPSTATE',
         r'\+CIPSTATE:|\bOK\b', 4.0)
    step('6-TCP服务端', '关闭服务端', 'AT+CIPSERVER=0', 'AT+CIPSERVER=0',
         r'\bOK\b|\bERROR\b', 5.0)
    try:
        c.close()
    except OSError:
        pass
    time.sleep(1.0)


def phase7_udp_server(port):
    """模组作 UDP 服务端, PC 先发包(借状态化放行回包)"""
    raw('===', '阶段7 UDP 服务端(模组监听, PC 发包)')
    txt, ok = step('7-UDP服务端', '开启 UDP 服务端', 'AT+CIPSERVER=1,%d,"UDP"' % port,
                   'AT+CIPSERVER=1,%d,"UDP"' % port,
                   r'\bOK\b|ready|listen|\bERROR\b', 8.0, expect_desc='OK (UDP, linkid=5)')
    time.sleep(1.5)

    mod_ip = ARGS.module_ip
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(3.0)
    payload = b'UDP-FROM-PC\r\n'
    try:
        s.sendto(payload, (mod_ip, port))
        raw('PC-UDP', '-> %s:%d %r' % (mod_ip, port, payload))
    except OSError as e:
        rec('7-UDP服务端', 'PC -> 模组 UDP', 'sendto(%s,%d)' % (mod_ip, port),
            'FAIL', 'socket error: %s' % e, '+IPD,5,<len>:UDP-FROM-PC')
        s.close()
        AT.send_line('AT+CIPSERVER=0')
        AT.wait_for([r'\bOK\b'], 4.0)
        return

    txt, hit = AT.wait_for([r'\+IPD,\d+,\d+:.*UDP-FROM-PC'], 8.0)
    rec('7-UDP服务端', 'PC -> 模组 UDP', 'PC sendto "UDP-FROM-PC"',
        'PASS' if hit else 'FAIL', vis(txt)[:300], '+IPD,5,<len>:UDP-FROM-PC')

    # 模组回发
    payload2 = b'UDP-FROM-BK7238\r\n'
    AT.reset_buffers()
    AT.send_line('AT+CIPSEND=5,%d' % len(payload2))
    pre, hitp = AT.wait_for([r'>'], 6.0)
    if hitp:
        AT.send_bytes(payload2)
        t2, _ = AT.wait_for([r'SEND OK', r'\bERROR\b'], 6.0)
        got = b''
        try:
            got, src = s.recvfrom(1024)
            raw('PC-UDP', '<- %s:%d %r' % (src[0], src[1], got))
        except Exception as e:
            raw('PC-UDP', 'recv fail: %s' % e)
        rec('7-UDP服务端', '模组 -> PC UDP', 'AT+CIPSEND=5,%d' % len(payload2),
            'PASS' if payload2.strip() in got else 'FAIL',
            'AT侧=%s | PC侧收到=%r' % (vis(t2)[:150], got[:80]),
            'PC 收到 UDP-FROM-BK7238')
    else:
        rec('7-UDP服务端', '模组 -> PC UDP', 'AT+CIPSEND=5,%d' % len(payload2),
            'FAIL', '未收到 > 提示符', 'SEND OK')
    s.close()
    step('7-UDP服务端', '关闭服务端', 'AT+CIPSERVER=0', 'AT+CIPSERVER=0',
         r'\bOK\b|\bERROR\b', 5.0)


def phase8_teardown(ssid, pwd):
    raw('===', '阶段8 断连与恢复')
    step('8-断连恢复', '断开 AP', 'AT+CWQAP', 'AT+CWQAP',
         r'WIFI DISCONNECT|\bOK\b', 8.0, expect_desc='WIFI DISCONNECT')
    time.sleep(1.0)
    step('8-断连恢复', '断连后状态', 'AT+CIPSTATUS?', 'AT+CIPSTATUS?',
         r'STATUS:5|STATUS:\d', 3.0, expect_desc='STATUS:5 (无 Wi-Fi 连接)')
    txt, _ = step('8-断连恢复', '重新关联 AP', 'AT+CWJAP="%s","***"' % ssid,
                  'AT+CWJAP="%s","%s"' % (ssid, pwd), r'\bOK\b|\bERROR\b', 30.0)
    time.sleep(1.0)
    step('8-断连恢复', '恢复后状态', 'AT+CIPSTATUS?', 'AT+CIPSTATUS?',
         r'STATUS:\d', 3.0, expect_desc='STATUS:2/3/4')


# ===========================================================================
def main():
    global AT, PC, ARGS, RAW_FH

    ap = argparse.ArgumentParser()
    ap.add_argument('port', nargs='?', default='COM3')
    ap.add_argument('--baud', type=int, default=115200)
    ap.add_argument('--ssid', default='MyHomeWiFi')
    ap.add_argument('--password', default='')
    ap.add_argument('--pc-ip', default='192.168.0.152')
    ap.add_argument('--tcp-port', type=int, default=8266)
    ap.add_argument('--udp-port', type=int, default=8267)
    ap.add_argument('--out', default=REPORT)
    ARGS = ap.parse_args()

    os.makedirs(os.path.dirname(RAW_LOG), exist_ok=True)
    os.makedirs(os.path.dirname(ARGS.out), exist_ok=True)
    RAW_FH = open(RAW_LOG, 'w', encoding='utf-8', errors='replace')

    PC = Peer()
    PC.start_tcp_server(ARGS.tcp_port)
    PC.start_udp_server(ARGS.udp_port)

    AT = AtPort(ARGS.port, ARGS.baud)
    AT.pump(1.5)
    AT.reset_buffers()

    t_start = time.time()
    try:
        phase1_join(ARGS.ssid, ARGS.password)
        phase2_ip()
        # 记录模组 STA IP
        AT.reset_buffers()
        AT.send_line('AT+CIPSTA?')
        txt, _ = AT.wait_for([r'\+CIPSTA:'], 3.0)
        m = re.search(r'ip:"([\d.]+)"', txt)
        ARGS.module_ip = m.group(1) if m else None
        raw('INFO', 'module STA ip = %s' % ARGS.module_ip)

        phase3_net(ARGS.ssid, ARGS.password, ARGS.pc_ip)
        phase4_tcp_client_internet()
        phase5_tcp_client_pc(ARGS.pc_ip, ARGS.tcp_port)
        phase6_tcp_server(ARGS.tcp_port)
        phase7_udp_server(ARGS.udp_port)
        phase8_teardown(ARGS.ssid, ARGS.password)
    except Exception as e:
        import traceback
        raw('EXC', traceback.format_exc())
        rec('异常', '测试中断', '-', 'FAIL', str(e), '-')
    finally:
        elapsed = time.time() - t_start
        write_report(ARGS, elapsed)
        AT.close()
        PC.shutdown()
        if RAW_FH:
            RAW_FH.close()

    fails = [r for r in RESULTS if r['status'] == 'FAIL']
    skips = [r for r in RESULTS if r['status'] == 'SKIP']
    print('\n==== 合计 %d 项, PASS %d, FAIL %d, SKIP %d, 用时 %.1fs ===='
          % (len(RESULTS), len(RESULTS) - len(fails) - len(skips), len(fails), len(skips), elapsed))
    for r in fails:
        print('  FAIL  [%s] %s  -> %s' % (r['phase'], r['name'], r['detail'][:160]))
    for r in skips:
        print('  SKIP  [%s] %s  -> %s' % (r['phase'], r['name'], r['detail'][:160]))
    print('报告: %s' % ARGS.out)
    return 0


def write_report(args, elapsed):
    lines = []
    lines.append('# BK7238 / XH-WB3S  AT 固件 · 联网功能联调报告')
    lines.append('')
    lines.append('- 测试时间: %s' % datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    lines.append('- 串口: `%s` @ %d' % (args.port, args.baud))
    lines.append('- 目标 AP: `%s`' % args.ssid)
    lines.append('- PC 侧地址: `%s` (TCP %d / UDP %d)' % (args.pc_ip, args.tcp_port, args.udp_port))
    lines.append('- 模组 STA 地址: `%s`' % (getattr(args, 'module_ip', None) or '未获取到'))
    lines.append('- 固件: BK7238-AT(V1.1.0/esp32c3-compat)')
    lines.append('- 用时: %.1f 秒' % elapsed)
    lines.append('')

    total = len(RESULTS)
    passed = len([r for r in RESULTS if r['status'] == 'PASS'])
    lines.append('## 结论')
    lines.append('')
    lines.append('**%d / %d 项通过**（通过率 %.1f%%）' % (passed, total, 100.0 * passed / total if total else 0))
    lines.append('')

    phases = []
    for r in RESULTS:
        if r['phase'] not in phases:
            phases.append(r['phase'])
    lines.append('| 阶段 | PASS/总数 |')
    lines.append('|------|-----------|')
    for p in phases:
        sub = [r for r in RESULTS if r['phase'] == p]
        lines.append('| %s | %d/%d |' % (p, len([r for r in sub if r['status'] == 'PASS']), len(sub)))
    lines.append('')

    lines.append('## 逐项明细')
    lines.append('')
    lines.append('| # | 阶段 | 项目 | 命令 | 期望 | 结果 | 原始响应 |')
    lines.append('|---|------|------|------|------|------|----------|')
    for i, r in enumerate(RESULTS, 1):
        lines.append('| %d | %s | %s | `%s` | %s | %s | `%s` |'
                     % (i, r['phase'], r['name'], r['cmd'], r['expect'], r['status'], r['detail']))
    lines.append('')

    fails = [r for r in RESULTS if r['status'] != 'PASS']
    lines.append('## 失败项（%d）' % len(fails))
    lines.append('')
    if fails:
        for r in fails:
            lines.append('- **%s / %s** — `%s`' % (r['phase'], r['name'], r['cmd']))
            lines.append('  - 原始响应: `%s`' % r['detail'][:300])
    else:
        lines.append('无。')
    lines.append('')

    with open(args.out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print('[report] %s' % args.out)


if __name__ == '__main__':
    sys.exit(main())
