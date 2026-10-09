# -*- coding: utf-8 -*-
"""MICRO16: 精确刻画 "显式 bind 本地端口 -> RX 死" 的触发条件。
全程用【高端口】排除低位端口干扰:
  A1 显式 lport 20000 (第一个 socket)      -> echo
  A2 CIPCLOSE=5 -> 显式 lport 20005        -> echo
  A3 CIPCLOSE=5 -> 显式 lport 20000 (复用) -> echo
  A4 CIPCLOSE=5 -> lport 0 (自动)          -> echo
  A5 RST -> 显式 lport 20010               -> echo
打印每次 sendto 返回值 + 逐次尝试结果。
"""
import sys, os, time, re, socket
sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PC_IP = "192.168.0.152"
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)
a = AT("MICRO16", "COM5", LOGDIR)

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
    hits = 0; snd_ok = 0
    if addr:
        for _ in range(5):
            try:
                n = uc.sendto(payload, (addr[0], addr[1]))
                snd_ok += 1 if n == len(payload) else 0
            except OSError as e:
                print("    sendto err:", e)
            t0 = time.time()
            while time.time() - t0 < 1.0:
                a.pump(0.15)
                if re.search(rb"\+IPD,1,10", a.buf):
                    hits += 1; break
    print("  [%s] 建连=%s TX=%s peer=%s sendto_ok=%d/5 RX=%d/5" % (
        tag, st, "OK" if addr else "FAIL",
        ("%s:%d" % (addr[0], addr[1])) if addr else "-", snd_ok, hits))
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

try:
    connect()
    print("== A1 显式 20000 (首 socket) ==")
    echo(50310, 20000, "A1-20000")
    print("== A2 CIPCLOSE=5 -> 显式 20005 ==")
    cmd("AT+CIPCLOSE=5", 4); time.sleep(2)
    echo(50311, 20005, "A2-20005")
    print("== A3 CIPCLOSE=5 -> 显式 20000 复用 ==")
    cmd("AT+CIPCLOSE=5", 4); time.sleep(2)
    echo(50312, 20000, "A3-20000(#2)")
    print("== A4 CIPCLOSE=5 -> lport0 自动 ==")
    cmd("AT+CIPCLOSE=5", 4); time.sleep(2)
    echo(50313, 0, "A4-auto")
    print("== A5 RST -> 显式 20010 ==")
    cmd("AT+RST", 6); time.sleep(6); a.pump(1.0); a.clear()
    connect()
    echo(50314, 20010, "A5-20010")
    cmd("AT+CIPCLOSE=5", 4)
finally:
    a.close()
