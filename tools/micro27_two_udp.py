# -*- coding: utf-8 -*-
"""MICRO27: 精确复刻文档 2.4 的 UDP 多连接场景, 分离"端口值"与"两个 link 相互作用"。

文档 2.4 的命令序列:
   AT+CIPMUX=1
   AT+CIPSTART=0,"UDP","255.255.255.255",50000,1000,0     <- link0 广播
   AT+CIPSEND=0,10 + sparkleiot                          <- PC(50000) 收到 OK
   AT+CIPSTART=1,"UDP","<PC>",50001,1001,0                <- link1 单播
   AT+CIPSEND=1,10 + sparkleiot                          <- PC(50001) 收到 OK
   PC 回发 3 次到 link1 的对端地址                         <- 实测收不到(FAIL)

用法:
   python tools/micro27_two_udp.py COM5 1000 1001        # 复刻 2.4 (预期可复现 FAIL)
   python tools/micro27_two_udp.py COM5 1000 1010        # 只换 link1 端口 -> 判"端口值"是否相关
   python tools/micro27_two_udp.py COM5 0 1010 --nolink0 # 去掉 link0 -> 判"两个 link 相互作用"
"""
import os
import re
import sys
import time
import socket

sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PC_IP = "192.168.0.152"
SSID = "MyHomeWiFi"
PWD = os.environ.get("BK7238_WIFI_PWD", "<WIFI_PWD>")
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)

COM = sys.argv[1] if len(sys.argv) > 1 else "COM5"
LPORT0 = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
LPORT1 = int(sys.argv[3]) if len(sys.argv) > 3 else 1001
REPS = int(sys.argv[4]) if len(sys.argv) > 4 else 4
NO_LINK0 = "--nolink0" in sys.argv
PCPORT0, PCPORT1 = 50000, 50001

a = AT("MICRO27", COM, LOGDIR)


def cmd(line, t=8):
    a.clear()
    a.send(line=line)
    acc = ""
    t0 = time.time()
    while time.time() - t0 < t:
        acc += a.pump(0.2)
        if re.search(r"OK\r?\n", acc):
            return "OK"
        if "ERROR" in acc:
            return "ERROR"
    return "TIMEOUT"


cmd("ATE0", 2)
cmd("AT+CWMODE=1", 6)
cmd('AT+CWJAP="%s","%s"' % (SSID, PWD), 25)
t0 = time.time()
while time.time() - t0 < 25:
    if "GOT IP" in a.pump(0.3):
        break
time.sleep(2)
a.clear()
cmd("AT+CIPMUX=1", 6)
print("配置: lport0=%s lport1=%d  link0=%s  reps=%d" %
      ("(跳过)" if NO_LINK0 else LPORT0, LPORT1, "OFF" if NO_LINK0 else "ON", REPS))

PAY = b"SparkleIOT"
rows = []
for r in range(1, REPS + 1):
    cmd("AT+CIPCLOSE=5", 5)
    time.sleep(1.2)
    s0 = s1 = None
    try:
        # ---------- link 0: 广播 ----------
        bcast_ok = "-"
        if not NO_LINK0:
            s0 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s0.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s0.bind(("", PCPORT0)); s0.settimeout(0.3)
            st = cmd('AT+CIPSTART=0,"UDP","255.255.255.255",%d,%d,0' % (PCPORT0, LPORT0))
            a.clear(); a.send(line="AT+CIPSEND=0,10")
            time.sleep(0.6); a.pump(0.3); a.clear(); a.send(raw=b"sparkleiot")
            t0 = time.time(); got0 = False
            while time.time() - t0 < 2.5:
                try:
                    s0.recvfrom(2048); got0 = True; break
                except socket.timeout:
                    pass
            bcast_ok = "收" if got0 else "丢"
            if st != "OK":
                bcast_ok += "/START" + st

        # ---------- link 1: 单播 ----------
        s1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s1.bind(("", PCPORT1)); s1.settimeout(0.3)
        st1 = cmd('AT+CIPSTART=1,"UDP","%s",%d,%d,0' % (PC_IP, PCPORT1, LPORT1))
        a.clear(); a.send(line="AT+CIPSEND=1,10")
        time.sleep(0.6); a.pump(0.3); a.clear(); a.send(raw=b"sparkleiot")
        t0 = time.time(); addr = None
        while time.time() - t0 < 2.5:
            try:
                _, addr = s1.recvfrom(2048); break
            except socket.timeout:
                pass
        tx_ok = "收" if addr else "丢"
        # ---------- PC -> 模组 单播回发 ----------
        got = 0
        if addr:
            seen = len(re.findall(rb"\+IPD,1,10", a.buf))
            for _ in range(3):
                s1.sendto(PAY, (addr[0], addr[1]))
                t0 = time.time()
                while time.time() - t0 < 1.2:
                    a.pump(0.12)
                    now = len(re.findall(rb"\+IPD,1,10", a.buf))
                    if now > seen:
                        got += 1; seen = now; break
        rows.append((r, bcast_ok, st1, tx_ok, addr, got))
        print("  #%-2d link0=%-8s link1START=%-6s TX=%-4s 对端=%-22s 模组收到 %d/3" %
              (r, bcast_ok, st1, tx_ok, str(addr), got))
    finally:
        if s0: s0.close()
        if s1: s1.close()

a.close()
ok = sum(1 for _, _, _, _, _, g in rows if g > 0)
print("\n== 汇总: 模组收到单播回发的轮次 %d/%d ==" % (ok, REPS))
