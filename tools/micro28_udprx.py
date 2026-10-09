# -*- coding: utf-8 -*-
"""MICRO28: UDP RX 配置矩阵 —— 分离 CIPMUX / CIPMODE / 本地端口 三个变量。

对每组配置:
  1. 设定 CIPMUX / CIPMODE
  2. CIPSTART UDP -> PC:pcport lport=<lport>
  3. 发 10B 让 PC 学到模组的真实源地址(含端口)
  4. PC 回发 payload x N 到 (模组IP, lport)
  5. 统计模组 UART 上出现了几个 payload (mode0 在 +IPD 后 / mode1 裸输出)

判读:
  * 某组 RX 全通 vs 另一组全丢 => 差异变量即根因。
  * 若 CIPMODE=1 组丢而 CIPMODE=0 组通 => 透传模式 RX 路径有 bug。

用法: python tools/micro28_udprx.py [COM5]
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
PCPORT = 5000
PAYLOAD = b"SparkleIOT"   # 36 bytes
N = 5

COM = sys.argv[1] if len(sys.argv) > 1 else "COM5"
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)

a = AT("MICRO28", COM, LOGDIR)


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


def pump_for(t):
    acc = ""
    t0 = time.time()
    while time.time() - t0 < t:
        acc += a.pump(0.2)
    return acc


def cleanup():
    """退出透传 + 关掉所有链路 + 回到 COMMON"""
    a.send(raw=b"+++")
    time.sleep(1.3)
    a.pump(0.5)
    cmd("AT", 3)
    cmd("ATE0", 2)
    cmd("AT+CIPMODE=0", 4)
    for i in range(6):
        cmd("AT+CIPCLOSE=%d" % i, 2)
    cmd("AT+CIPCLOSE=5", 3)
    cmd("AT+CIPMODE=0", 3)


# ---- 关联 ----
cmd("ATE0", 2)
cmd("AT+CWMODE=1", 6)
cmd('AT+CWJAP="%s","%s"' % (SSID, PWD), 25)
t0 = time.time()
while time.time() - t0 < 25:
    if "GOT IP" in a.pump(0.3):
        break
time.sleep(2)
a.clear()
_, ipout = cmd("AT+CIPSTA?", 4)
m = re.search(r'\+CIPSTA:ip:"([\d.]+)"', ipout)
MODIP = m.group(1) if m else None
print("模组 IP =", MODIP, " PC =", PC_IP, " cp =", PCPORT)
if not MODIP or MODIP == "0.0.0.0":
    print("!! 模组没拿到 IP, 终止")
    a.close()
    sys.exit(1)

CFGS = [
    ("mux0_mode0_lp2000", 0, 0, 2000),
    ("mux1_mode0_lp1001", 1, 0, 1001),
    ("mux1_mode0_lp2000", 1, 0, 2000),
    ("mux0_mode1_lp2000", 0, 1, 2000),
    ("mux0_mode1_lp1001", 0, 1, 1001),
]

results = []
for name, mux, mode, lport in CFGS:
    cleanup()
    cmd("AT+CIPMUX=%d" % mux, 4)
    cmd("AT+CIPMODE=%d" % mode, 4)

    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    u.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    u.bind(("", PCPORT))
    u.settimeout(0.3)

    if mux == 1:
        line = 'AT+CIPSTART=0,"UDP","%s",%d,%d,0' % (PC_IP, PCPORT, lport)
    else:
        line = 'AT+CIPSTART="UDP","%s",%d,%d,0' % (PC_IP, PCPORT, lport)

    if mode == 1:
        # 透传: CIPSTART 在 passthrough env 下不回 OK(由收线程静默建连)
        a.clear()
        a.send(line=line)
        acc = pump_for(4)          # 等 ~4s 建连
        st = "NOERR" if "ERROR" not in acc else "ERROR"
        # 进入透传: AT+CIPSEND(无参) -> '>'
        _, acc2 = cmd("AT+CIPSEND", 5)
        entered = ">" in acc2
        a.clear()
        a.send(raw=b"sparkleiot")
        time.sleep(1.2)
        a.pump(0.4)
    else:
        st, acc = cmd(line, 12)
        entered = True
        # 普通发送
        a.clear()
        if mux == 1:
            a.send(line="AT+CIPSEND=0,10")
        else:
            a.send(line="AT+CIPSEND=10")
        time.sleep(0.7)
        got_prompt = ">" in a.pump(0.4)
        a.clear()
        a.send(raw=b"sparkleiot")
        time.sleep(1.2)
        a.pump(0.4)
        entered = entered and got_prompt

    # PC 学对端
    peer = None
    t0 = time.time()
    while time.time() - t0 < 3:
        try:
            _, peer = u.recvfrom(2048)
            break
        except socket.timeout:
            pass

    if not peer:
        results.append((name, st, entered, "(PC 没收到首次数据)", 0))
        u.close()
        continue

    a.clear()
    seen = len(re.findall(re.escape(PAYLOAD), a.buf))
    got = 0
    for _ in range(N):
        u.sendto(PAYLOAD, (peer[0], lport))
        t0 = time.time()
        while time.time() - t0 < 1.2:
            a.pump(0.12)
            now = len(re.findall(re.escape(PAYLOAD), a.buf))
            if now > seen:
                got += 1
                seen = now
                break
    results.append((name, st, entered, "peer=%s:%d" % peer, got))
    u.close()

a.close()

print("\n%-22s %-8s %-9s %-30s RX" % ("配置", "CIPSTART", "进入透传", "PC学到对端"))
for name, st, entered, peer, got in results:
    print("%-22s %-8s %-9s %-30s %d/%d %s" %
          (name, st, "Y" if entered else "N", peer, got, N,
           "" if got == N else ("  <== 全丢" if got == 0 else "  <== 部分丢")))
