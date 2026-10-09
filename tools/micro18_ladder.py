# -*- coding: utf-8 -*-
"""MICRO18: #13 收包链路阶梯探针实验。

流程:
  A1  lport=1010 首次建连 -> 应收到 (基线)
  A2  CIPCLOSE=5 -> lport=1010 重建 -> 应"未收到" (毒化)
  全程 ATE1, 原始字节落盘 test/micro18_raw.log, 用于定位丢包发生在哪一层:
    [MSDUIN]  驱动->lwIP 边界 (da/sa/本vif mac)
    [EIFIN]   port/ethernetif_input (da vs netif hwaddr)
    [ETHIN]   lwIP ethernet_input
    [IP4IN]   ip4_input
    [UDPIN]   udp_input
    [UDPNOPCB]/[UDPPCB] 无匹配 pcb + pcb 链 dump
    [UDPNEW]/[UDPBIND]/[UDPRM] pcb 生命周期
    [CLOSE]/[CLOSEDONE] socket 关闭是否真的完成
"""
import sys, os, time, re, socket
sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PC_IP = "192.168.0.152"
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)
RAW = open("test/micro18_raw.log", "wb")

a = AT("MICRO18", "COM5", LOGDIR)


def pump(dt=0.2):
    t = a.pump(dt)
    if t:
        RAW.write(t.encode("utf-8", "replace"))
        RAW.flush()
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


def mark(tag):
    RAW.write(("\n===== %s =====\n" % tag).encode())
    RAW.flush()
    print("== %s ==" % tag)


def echo(pcport, lport, tag):
    uc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    uc.bind(("", pcport)); uc.settimeout(0.3)
    st, _ = cmd('AT+CIPSTART=1,"UDP","%s",%d,%d,0' % (PC_IP, pcport, lport))
    a.clear(); a.send(line="AT+CIPSEND=1,10")
    time.sleep(0.8); pump(0.3); a.clear(); a.send(raw=b"sparkleiot")
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
            mark("%s -> sendto %s:%d" % (tag, addr[0], addr[1]))
            uc.sendto(payload, (addr[0], addr[1]))
            t0 = time.time()
            while time.time() - t0 < 3:
                pump(0.2)
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
    RAW.write(b"\n########## CIFSR ##########\n")
    cmd("AT+CIFSR", 6)
    mark("A1 lport1010 基线")
    echo(50230, 1010, "A1基线")
    mark("A2 CIPCLOSE=5 后 lport1010 重建")
    cmd("AT+CIPCLOSE=5", 4); time.sleep(2)
    echo(50231, 1010, "A2毒化")
    mark("A3 CIPSTATUS")
    cmd("AT+CIPSTATUS", 5)
    RAW.write(b"\n########## DONE ##########\n")
finally:
    RAW.close()
    a.close()
