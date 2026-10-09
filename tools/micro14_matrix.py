# -*- coding: utf-8 -*-
"""MICRO14: 毒化矩阵判别
  P1 基线           : fresh UDP lport1001 -> echo (期望 OK)
  P2 CIPCLOSE=5重建 : lport1001             -> echo (期望 死)
  P3 (毒化态)       : lport1005(全新端口)   -> echo ?
  P4 (毒化态)       : lport0(不 bind)       -> echo ?  (PC 学源端口)
  P5 (毒化态)       : TCP client RX          -> +IPD ?
  P6 RST 对照       : fresh UDP lport1001    -> echo
判别: 全局 RX 死 / 仅同端口死 / 仅 UDP 死。
"""
import sys, os, time, re, socket, threading
sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PC_IP = "192.168.0.152"
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)
a = AT("MICRO14", "COM5", LOGDIR)

def cmd(line, t=8):
    a.clear(); a.send(line=line)
    t0 = time.time(); acc = ""
    while time.time() - t0 < t:
        acc += a.pump(0.2)
        if re.search(r"OK\r?\n", acc):
            return "OK", acc
        if "ERROR" in acc:
            return "ERROR", acc
    return "TIMEOUT", acc

def udp_echo(pcport, lport, tag):
    uc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    uc.bind(("", pcport)); uc.settimeout(0.3)
    st, _ = cmd('AT+CIPSTART=1,"UDP","%s",%d,%d,0' % (PC_IP, pcport, lport))
    a.clear(); a.send(line="AT+CIPSEND=1,10")
    time.sleep(0.8); a.pump(0.3); a.clear(); a.send(raw=b"sparkleiot")
    t0 = time.time(); addr = None
    while time.time() - t0 < 4:
        try:
            _, addr = uc.recvfrom(2048); break
        except socket.timeout:
            pass
    payload = b"SparkleIOT"
    r = None
    if addr:
        for _ in range(2):
            uc.sendto(payload, (addr[0], addr[1]))
            t0 = time.time()
            while time.time() - t0 < 4:
                a.pump(0.2)
                if re.search(rb"\+IPD,1,10", a.buf):
                    r = True; break
            if r:
                break
    print("  [%s] 建连=%s TX=%s echo=%s peer=%s" % (
        tag, st, "OK" if addr else "FAIL", u"收到" if r else u"未收到",
        ("%s:%d" % (addr[0], addr[1])) if addr else "-"))
    uc.close()
    return r is not None

def tcp_rx(tag):
    """PC 作 TCP server, 模块连入, PC 发 data, 看模块 +IPD"""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("", 50130)); srv.listen(1); srv.settimeout(6)
    st, _ = cmd('AT+CIPSTART=1,"TCP","%s",50130' % PC_IP, 8)
    conn = None
    try:
        conn, _ = srv.accept()
    except socket.timeout:
        pass
    ok = False
    if conn:
        conn.sendall(b"HELLO-TCP-RX")
        t0 = time.time()
        while time.time() - t0 < 5:
            a.pump(0.2)
            if b"HELLO-TCP-RX" in a.buf:
                ok = True; break
        conn.close()
    print("  [%s] TCP建连=%s RX=%s" % (tag, st, "OK" if ok else "死"))
    srv.close()
    return ok

def connect():
    cmd("ATE1", 4)   # 打开 bk_printf 日志门控, 让 UDP 探针可见
    cmd("AT+CWMODE=1", 6)
    cmd('AT+CWJAP="MyHomeWiFi","<WIFI_PWD>"', 25)
    t0 = time.time()
    while time.time() - t0 < 20:
        if "GOT IP" in a.pump(0.3):
            break
    time.sleep(2); a.clear()
    cmd("AT+CIPMUX=1", 6)

try:
    connect()
    print("== P1 基线 UDP lport1001 ==")
    udp_echo(50140, 1001, "P1基线")
    print("== P2 CIPCLOSE=5 重建 lport1001 ==")
    cmd("AT+CIPCLOSE=5", 4); time.sleep(2)
    udp_echo(50141, 1001, "P2重建")
    print("== P3 毒化态: 全新 lport1005 ==")
    cmd("AT+CIPCLOSE=5", 4); time.sleep(2)
    udp_echo(50142, 1005, "P3新端口")
    print("== P4 毒化态: lport0(不 bind) ==")
    cmd("AT+CIPCLOSE=5", 4); time.sleep(2)
    udp_echo(50143, 0, "P4不bind")
    print("== P5 毒化态: TCP RX ==")
    cmd("AT+CIPCLOSE=5", 4); time.sleep(2)
    tcp_rx("P5TCP")
    cmd("AT+CIPCLOSE=5", 4)
    print("== P6 RST 对照: UDP lport1001 ==")
    cmd("AT+RST", 6); time.sleep(6); a.pump(1.0); a.clear()
    connect()
    udp_echo(50144, 1001, "P6复位后")
    cmd("AT+CIPCLOSE=5", 4)
finally:
    a.close()
