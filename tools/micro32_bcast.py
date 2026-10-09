# -*- coding: utf-8 -*-
"""MICRO32: 模组 -> PC 广播 vs 单播 (含“PC 先发热包”对照)。

流程: CIPMUX=1
  link0 = UDP 广播 255.255.255.255:50000 (lport 1000)
  link1 = UDP 单播 PC:50001              (lport 1001)
对 link0 / link1 各测:
  A) 不发热包, 模组直接 CIPSEND -> PC 是否收到?
  B) PC 先 sendto 到 (模组IP, lport) 一次(开防火墙状态孔/让模组学 MAC)
     再 CIPSEND -> PC 是否收到?

用法: <python> tools/micro32_bcast.py COM5 [rounds]
"""
import os
import re
import sys
import time
import socket

sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PC_IP = "192.168.0.152"
COM = sys.argv[1] if len(sys.argv) > 1 else "COM5"
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 2
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)

print("解释器:", sys.executable)
a = AT("MICRO32", COM, LOGDIR)


def cmd(line, t=8):
    a.clear()
    a.send(line=line)
    t0 = time.time()
    acc = ""
    while time.time() - t0 < t:
        acc += a.pump(0.2)
        if re.search(r"OK\r?\n", acc):
            return "OK", acc
        if "ERROR" in acc:
            return "ERROR", acc
    return "TIMEOUT", acc


def recv_n(sock, n, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            d, addr = sock.recvfrom(4096)
            if d:
                return d, addr
        except socket.timeout:
            pass
    return None, None


cmd("ATE0", 2)
cmd("AT+CIPCLOSE=5", 3)
cmd("AT+CIPCLOSE", 3)
cmd("AT+CIPMODE=0", 3)
cmd("AT+CIPMUX=1", 4)

_, q = cmd("AT+CIPSTA?", 4)
m = re.search(r'\+CIPSTA:ip:"([\d.]+)"', q)
MODIP = m.group(1) if m else None
print("模组 IP:", MODIP)

bc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
bc.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
bc.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
bc.bind(("", 50000))
bc.settimeout(0.4)

uc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
uc.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
uc.bind(("", 50001))
uc.settimeout(0.4)

print("link0 CIPSTART:", cmd('AT+CIPSTART=0,"UDP","255.255.255.255",50000,1000,0', 10)[0])
print("link1 CIPSTART:", cmd('AT+CIPSTART=1,"UDP","%s",50001,1001,0' % PC_IP, 10)[0])


def send_link(linkid, n=11):
    st, acc = cmd("AT+CIPSEND=%d,%d" % (linkid, n), 5)
    if ">" not in acc:
        return False
    a.clear()
    a.send(raw=b"sparkleiot")
    time.sleep(1.0)
    a.pump(0.3)
    return True


for r in range(1, ROUNDS + 1):
    print("--- round %d ---" % r)
    # A) 广播, 无热包
    ok = send_link(0)
    d, ad = recv_n(bc, 1, 2.0)
    print("  广播 无热包: sent=%s PC收=%s" % (ok, "Y" if d else "N"))
    # B) 单播, 无热包
    ok = send_link(1)
    d, ad = recv_n(uc, 1, 2.0)
    print("  单播 无热包: sent=%s PC收=%s" % (ok, "Y" if d else "N"))
    # C) 广播, 先热
    bc.sendto(b"warm", (MODIP, 1000)); time.sleep(0.5)
    ok = send_link(0)
    d, ad = recv_n(bc, 1, 2.0)
    print("  广播 有热包: sent=%s PC收=%s" % (ok, "Y" if d else "N"))
    # D) 单播, 先热
    uc.sendto(b"warm", (MODIP, 1001)); time.sleep(0.5)
    ok = send_link(1)
    d, ad = recv_n(uc, 1, 2.0)
    print("  单播 有热包: sent=%s PC收=%s  (src=%s)" % (ok, "Y" if d else "N", ad))

cmd("AT+CIPCLOSE=5", 3)
cmd("AT+CIPCLOSE", 3)
a.close()
bc.close()
uc.close()
