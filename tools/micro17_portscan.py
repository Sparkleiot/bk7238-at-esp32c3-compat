# -*- coding: utf-8 -*-
"""MICRO17: 本地端口阈值扫描 (每个端口前 RST 隔离, 排除状态污染)。
对每个候选本地端口: RST -> 重连 -> bind(port) -> echo。
判定哪些端口值会导致 UDP RX 死。
"""
import sys, os, time, re, socket
sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PC_IP = "192.168.0.152"
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)
a = AT("MICRO17", "COM5", LOGDIR)

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

def echo(pcport, lport, tag):
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
    hits = 0
    if addr:
        for _ in range(3):
            try:
                uc.sendto(payload, (addr[0], addr[1]))
            except OSError:
                pass
            t0 = time.time()
            while time.time() - t0 < 1.2:
                a.pump(0.15)
                if re.search(rb"\+IPD,1,10", a.buf):
                    hits += 1; break
    print("  [%s] 建连=%s TX=%s peer=%s RX=%s" % (
        tag, st, "OK" if addr else "FAIL",
        ("%s:%d" % (addr[0], addr[1])) if addr else "-",
        "收到" if hits else "未收到"))
    uc.close()
    return hits > 0

def connect():
    cmd("ATE1", 4)
    cmd("AT+CWMODE=1", 6)
    cmd('AT+CWJAP="MyHomeWiFi","<WIFI_PWD>"', 25)
    t0 = time.time()
    while time.time() - t0 < 20:
        if "GOT IP" in a.pump(0.3):
            break
    time.sleep(2); a.clear()
    cmd("AT+CIPMUX=1", 6)

def reset_and_connect():
    cmd("AT+RST", 6); time.sleep(6); a.pump(1.0); a.clear()
    connect()

PORTS = [8080, 5000, 2048, 1024, 1023, 1000, 3000, 2000]
try:
    connect()
    for i, p in enumerate(PORTS):
        print("== 端口 %d ==" % p)
        if i > 0:
            reset_and_connect()
        echo(50400 + i, p, "port%d" % p)
    cmd("AT+CIPCLOSE=5", 4)
finally:
    a.close()
