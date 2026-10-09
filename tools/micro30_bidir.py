# -*- coding: utf-8 -*-
"""MICRO30: 双向 UDP 判定 —— 分离"模组没发" vs "PC 入站被防火墙拦"。

流程 (CIPMUX=0, CIPMODE=0, lport=<lport>):
  1. CIPSTART UDP -> PC:pcport
  2. PC 先 sendto 模组 lport x N          -> 统计模组 RX (PC->模组方向)
     (PC 先发会在有状态防火墙上开一个孔: pc:pcport <-> 模组:lport)
  3. 模组 CIPSEND 10B                     -> PC 是否收到 (模组->PC 方向)
  4. 模组再 CIPSEND x3                    -> 命中率

判读:
  * 2 通 + 3 不通 => 模组发送有问题(或被拦), 但 2 证明 L2 单播 OK。
  * 2、3 都通     => 先前的失败是防火墙"非请自来入站"拦截(PC 先发即可绕开)。
  * 2 不通         => 空口/模组 RX 问题。

用法: <python> tools/micro30_bidir.py COM5 [lport]
"""
import os
import re
import subprocess
import sys
import time
import socket

sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PC_IP = "192.168.0.152"
PCPORT = 5013
COM = sys.argv[1] if len(sys.argv) > 1 else "COM5"
LPORT = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)

PAYLOAD = b"SparkleIOT"   # 10B
N = 6

print("解释器:", sys.executable)

u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
u.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
u.bind(("", PCPORT))
u.settimeout(0.5)
print("PC 绑定 UDP :%d" % PCPORT)

a = AT("MICRO30", COM, LOGDIR)


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


def ping_loss(ip, n=3):
    try:
        o = subprocess.run("ping -n %d -w 1000 %s" % (n, ip), shell=True,
                           capture_output=True, timeout=40).stdout.decode("gbk", "replace")
        m = re.search(r"(\d+)\s*%", o)
        return int(m.group(1)) if m else -1
    except Exception:
        return -1


cmd("ATE0", 2)
cmd("AT+CIPCLOSE=5", 3)
cmd("AT+CIPCLOSE", 3)
cmd("AT+CIPMODE=0", 3)
cmd("AT+CIPMUX=0", 3)

st, _ = cmd('AT+CIPSTART="UDP","%s",%d,%d,0' % (PC_IP, PCPORT, LPORT), 12)
print("CIPSTART:", st)
if st != "OK":
    a.close()
    u.close()
    sys.exit(1)

mod_ip = None
_, q = cmd("AT+CIPSTA?", 4)
m = re.search(r'\+CIPSTA:ip:"([\d.]+)"', q)
mod_ip = m.group(1) if m else None
print("模组 IP:", mod_ip, " ping 丢包:", ping_loss(mod_ip), "%")

# ---------- 2) PC -> 模组 ----------
a.clear()
seen = len(re.findall(re.escape(PAYLOAD), a.buf))
rx = 0
for _ in range(N):
    u.sendto(PAYLOAD, (mod_ip, LPORT))
    t0 = time.time()
    while time.time() - t0 < 1.0:
        a.pump(0.1)
        now = len(re.findall(re.escape(PAYLOAD), a.buf))
        if now > seen:
            rx += 1
            seen = now
            break
print("PC -> 模组 : 模组收到 %d/%d" % (rx, N))

# ---------- 3) 模组 -> PC ----------
ok_tx = 0
for i in range(N):
    a.clear()
    a.send(line="AT+CIPSEND=10")
    time.sleep(0.6)
    pr = a.pump(0.3)
    a.clear()
    a.send(raw=b"sparkleiot")
    got = False
    t0 = time.time()
    while time.time() - t0 < 1.2:
        try:
            d, addr = u.recvfrom(2048)
            got = True
            break
        except socket.timeout:
            pass
    sa = "SEND OK" in ""  # 占位
    print("   第 %d 发: prompt=%s  PC收到=%s" % (i + 1, ">" in pr, "Y" if got else "N"))
    if got:
        ok_tx += 1
print("模组 -> PC : PC 收到 %d/%d" % (ok_tx, N))

cmd("AT+CIPCLOSE", 3)
a.close()
u.close()
