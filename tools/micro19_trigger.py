# -*- coding: utf-8 -*-
"""MICRO19: 确定性触发搜索。

重复 "CIPSTART(指定低端口) -> echo -> CIPCLOSE" N 轮, 每轮报告是否收到,
找出毒化从第几轮开始; 毒化后再试一轮 lport=0 看是否自愈。
对照组: 全部 lport=0。
用法: python tools/micro19_trigger.py [COM5] [bind|zero]
"""
import sys, os, time, re, socket
sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PC_IP = "192.168.0.152"
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
MODE = sys.argv[2] if len(sys.argv) > 2 else "bind"
LPORT = 1010 if MODE == "bind" else 0
RAW = open("test/micro19_%s_raw.log" % MODE, "wb")

a = AT("MICRO19", PORT, LOGDIR)


def pump(dt=0.2):
    t = a.pump(dt)
    if t:
        RAW.write(t.encode("utf-8", "replace")); RAW.flush()
    return t


def cmd(line, t=8):
    a.clear(); a.send(line=line)
    t0 = time.time(); acc = ""
    while time.time() - t0 < t:
        acc += pump(0.2)
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
    time.sleep(0.7); pump(0.3); a.clear(); a.send(raw=b"sparkleiot")
    t0 = time.time(); addr = None
    while time.time() - t0 < 3:
        try:
            _, addr = uc.recvfrom(2048); break
        except socket.timeout:
            pass
    payload = b"SparkleIOT"
    r = None
    if addr:
        for _ in range(3):
            RAW.write(("\n--- %s sendto %s:%d ---\n" % (tag, addr[0], addr[1])).encode())
            uc.sendto(payload, (addr[0], addr[1]))
            t0 = time.time()
            while time.time() - t0 < 2.5:
                pump(0.2)
                if re.search(rb"\+IPD,1,10", a.buf):
                    r = True; break
            if r:
                break
    print("  [%-14s] 建连=%s TX=%s echo=%s" % (
        tag, st, "OK" if addr else "FAIL", u"收到" if r else u"未收到"))
    uc.close()
    return r is not None


def connect():
    cmd("ATE1", 4)
    cmd("AT+CWMODE=1", 6)
    cmd('AT+CWJAP="MyHomeWiFi","<WIFI_PWD>"', 25)
    t0 = time.time()
    while time.time() - t0 < 20:
        if "GOT IP" in pump(0.3):
            break
    time.sleep(2); a.clear()
    cmd("AT+CIPMUX=1", 6)


try:
    connect()
    NROUND = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    print("== MODE=%s LPORT=%d ROUNDS=%d ==" % (MODE, LPORT, NROUND))
    for i in range(1, NROUND + 1):
        ok = echo(50400 + i, LPORT, "%s#%d" % (MODE, i))
        RAW.write(("\n### round %d echo=%s ###\n" % (i, ok)).encode())
        cmd("AT+CIPCLOSE=5", 4); time.sleep(1.0)
    print("== 毒化后试 lport=0 ==")
    echo(50490, 0, "after-lport0")
    RAW.write(b"\n########## DONE ##########\n")
finally:
    RAW.close()
    a.close()
