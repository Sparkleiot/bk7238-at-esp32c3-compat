# -*- coding: utf-8 -*-
"""MICRO13: CIPCLOSE=5 全关后, 分别的等待时长再重建:
  - 变体1: 立即重建(2s)     -> 已知死
  - 变体2: 等 15s 再重建
  - 变体3: 等 40s 再重建
  判别"CIPCLOSE 延迟毒化" vs "立即重建死锁" vs 永久毒化。
"""
import sys, os, time, re, socket
sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PC_IP = "192.168.0.152"
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)
a = AT("MICRO13", "COM5", LOGDIR)

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

def echo(pcport, tag):
    """重建 link1 + TX + 回发 echo"""
    uc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    uc.bind(("", pcport)); uc.settimeout(0.3)
    st, _ = cmd('AT+CIPSTART=1,"UDP","%s",%d,1001,0' % (PC_IP, pcport))
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
            uc.sendto(payload, (addr[0], 1001))
            t0 = time.time()
            while time.time() - t0 < 4:
                a.pump(0.2)
                if re.search(rb"\+IPD,1,10", a.buf):
                    r = True; break
            if r:
                break
    print("  [%s] 建连=%s TX=%s echo=%s" % (tag, st, "OK" if addr else "FAIL", u"收到" if r else u"未收到"))
    uc.close()
    return r is not None

try:
    cmd("ATE0", 4)
    cmd("AT+CWMODE=1", 6)
    cmd('AT+CWJAP="MyHomeWiFi","<WIFI_PWD>"', 25)
    t0 = time.time()
    while time.time() - t0 < 20:
        if "GOT IP" in a.pump(0.3):
            break
    time.sleep(2); a.clear()
    cmd("AT+CIPMUX=1", 6)
    echo(50110, "基线")
    # 变体2: CIPCLOSE=5 -> 等 15s -> 重建
    print("== 变体: 等15s ==")
    cmd("AT+CIPCLOSE=5", 4)
    time.sleep(15)
    echo(50111, "等15s后重建")
    # 变体3: CIPCLOSE=5 -> 等 40s -> 重建
    print("== 变体: 等40s ==")
    cmd("AT+CIPCLOSE=5", 4)
    time.sleep(40)
    echo(50112, "等40s后重建")
    # 变体4: RST 恢复对照
    print("== 变体: RST 对照 ==")
    cmd("AT+RST", 6); time.sleep(6); a.pump(1.0); a.clear()
    cmd("ATE0", 4)
    cmd('AT+CWJAP="MyHomeWiFi","<WIFI_PWD>"', 25)
    t0 = time.time()
    while time.time() - t0 < 20:
        if "GOT IP" in a.pump(0.3):
            break
    time.sleep(2); a.clear()
    cmd("AT+CIPMUX=1", 6)
    echo(50113, "RST后")
    cmd("AT+CIPCLOSE=5", 4)
finally:
    a.close()
