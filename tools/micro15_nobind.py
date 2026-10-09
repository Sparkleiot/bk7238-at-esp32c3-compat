# -*- coding: utf-8 -*-
"""MICRO15: 判别 #10(UDP bind) 是否为毒化元凶。
全程 local port = 0 (从不 bind, 退化为原厂行为):
  A1 lport0 基线 -> echo
  A2 CIPCLOSE=5 -> lport0 重建 -> echo
  A3 CIPCLOSE=5 -> lport1010(有 bind) -> echo   (对照)
  A4 RST -> lport0 -> echo
若 A2 也死 => bind 无辜, 毒化与本地端口无关。
"""
import sys, os, time, re, socket
sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PC_IP = "192.168.0.152"
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)
a = AT("MICRO15", "COM5", LOGDIR)

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
    r = None
    if addr:
        for _ in range(3):
            uc.sendto(payload, (addr[0], addr[1]))
            t0 = time.time()
            while time.time() - t0 < 3:
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

def connect():
    cmd("ATE1", 4)   # 开 bk_printf 门控, 探针可见
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
    print("== A1 lport0 基线(无 bind) ==")
    echo(50210, 0, "A1lport0基线")
    print("== A2 CIPCLOSE=5 -> lport0 重建(无 bind) ==")
    cmd("AT+CIPCLOSE=5", 4); time.sleep(2)
    echo(50211, 0, "A2lport0重建")
    print("== A3 CIPCLOSE=5 -> lport1010 重建(有 bind 对照) ==")
    cmd("AT+CIPCLOSE=5", 4); time.sleep(2)
    echo(50212, 1010, "A3bind重建")
    print("== A4 RST 对照 lport0 ==")
    cmd("AT+RST", 6); time.sleep(6); a.pump(1.0); a.clear()
    connect()
    echo(50213, 0, "A4RST后lport0")
    cmd("AT+CIPCLOSE=5", 4)
finally:
    a.close()
