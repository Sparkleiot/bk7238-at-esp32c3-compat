# -*- coding: utf-8 -*-
"""MICRO29: 模组 -> PC UDP 是否到达 —— 判别 Windows 防火墙(按可执行文件)是否拦截。

同一脚本用不同 python 解释器运行, 对比 PC 能否收到模组的 UDP。
若 A(python3.12/venv) 收不到、B(3.13.12) 收得到 => 防火墙入站规则按 exe 授权。

用法: <python.exe> tools/micro29_fw.py COM5 [lport]
"""
import os
import re
import sys
import time
import socket

sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PC_IP = "192.168.0.152"
PCPORT = 5012
COM = sys.argv[1] if len(sys.argv) > 1 else "COM5"
LPORT = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)

print("解释器:", sys.executable)

u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
u.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
u.bind(("", PCPORT))
u.settimeout(0.6)
print("已绑定 UDP :%d" % PCPORT)

a = AT("MICRO29", COM, LOGDIR)


def cmd(line, t=8):
    a.clear()
    a.send(line=line)
    t0 = time.time()
    acc = ""
    while time.time() - t0 < t:
        acc += a.pump(0.2)
        if re.search(r"OK\r?\n", acc):
            return "OK"
        if "ERROR" in acc:
            return "ERROR"
    return "TIMEOUT"


cmd("ATE0", 2)
cmd("AT+CIPCLOSE=5", 3)
cmd("AT+CIPCLOSE", 3)
cmd("AT+CIPMODE=0", 3)
cmd("AT+CIPMUX=0", 3)

st = cmd('AT+CIPSTART="UDP","%s",%d,%d,0' % (PC_IP, PCPORT, LPORT), 12)
print("CIPSTART:", st)
if st != "OK":
    a.close()
    u.close()
    sys.exit(1)

peer = None
for i in range(6):
    a.clear()
    a.send(line="AT+CIPSEND=10")
    time.sleep(0.6)
    a.pump(0.3)
    a.clear()
    a.send(raw=b"sparkleiot")
    t0 = time.time()
    while time.time() - t0 < 1.5:
        try:
            d, addr = u.recvfrom(2048)
            peer = addr
            print("第 %d 次发送 -> PC 收到 %r from %s" % (i + 1, d, addr))
            break
        except socket.timeout:
            pass
    if peer:
        break
    print("第 %d 次发送 -> 未收到" % (i + 1))

if peer:
    a.clear()
    payload = b"SparkleIOT"
    got = 0
    for _ in range(5):
        u.sendto(payload, (peer[0], LPORT))
        t0 = time.time()
        while time.time() - t0 < 1.0:
            a.pump(0.1)
            if payload in a.buf:
                got += 1
                a.buf = b""
                break
    print("回向 RX: 模组收到 %d/5" % got)

cmd("AT+CIPCLOSE", 3)
a.close()
u.close()
