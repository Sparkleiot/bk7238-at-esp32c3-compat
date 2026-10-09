# -*- coding: utf-8 -*-
"""MICRO28b: UDP RX —— 普通模式 vs 透传模式 同窗口交替对照。

背景: 文档 2.4(普通, CIPMUX=1) 的 PC->模组单播 '曾经通过一次',
      而 2.5(透传, CIPMUX=0/CIPMODE=1) 三次全 FAIL。
      隔离运行里两者同窗口先后执行: 2.4 通、2.5 不通 => 疑似透传 RX 专属问题。

本实验把两种配置交替各跑 N 轮, 每轮都:
  1) 先做链路健康门控 (ping 模组, 丢包 >30% 就重试)
  2) 建链 + 发首包(带重试, 直到 PC 学到对端)
  3) PC 回发 payload x M, 统计模组收到几个

用法: python tools/micro28b_udprx.py [COM5] [rounds]
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
SSID = "MyHomeWiFi"
PWD = os.environ.get("BK7238_WIFI_PWD", "<WIFI_PWD>")
PCPORT = 5011
PAYLOAD = b"SparkleIOT"   # 36 bytes
M = 6

COM = sys.argv[1] if len(sys.argv) > 1 else "COM5"
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 4
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)

a = AT("MICRO28B", COM, LOGDIR)


def sh(c):
    try:
        return subprocess.run(c, shell=True, capture_output=True,
                              timeout=60).stdout.decode("gbk", "replace")
    except Exception as e:
        return "<err %s>" % e


def loss_pct(ip, n=3):
    o = sh("ping -n %d -w 1000 %s" % (n, ip))
    m = re.search(r"(\d+)\s*%", o)
    return int(m.group(1)) if m else -1


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
    a.send(raw=b"+++")
    time.sleep(1.3)
    a.pump(0.5)
    cmd("AT", 3)
    cmd("ATE0", 2)
    cmd("AT+CIPCLOSE=5", 4)
    cmd("AT+CIPCLOSE", 4)
    cmd("AT+CIPMODE=0", 4)


def healthy(ip, max_try=6):
    for _ in range(max_try):
        l = loss_pct(ip, 3)
        if 0 <= l <= 30:
            return l
        time.sleep(2)
    return -1


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
    print("!! 模组没拿到 IP")
    a.close()
    sys.exit(1)


def send_first(u, mux, mode):
    """发首包让 PC 学到模组地址; 返回 peer 或 None"""
    if mode == 1:
        a.send(raw=b"sparkleiot")
        time.sleep(0.8)
        a.pump(0.3)
    else:
        a.clear()
        a.send(line=("AT+CIPSEND=0,10" if mux else "AT+CIPSEND=10"))
        time.sleep(0.6)
        a.pump(0.3)
        a.clear()
        a.send(raw=b"sparkleiot")
        time.sleep(0.8)
        a.pump(0.3)
    try:
        _, peer = u.recvfrom(2048)
        return peer
    except socket.timeout:
        return None


def one_round(mux, mode, lport):
    """返回 (建连状态, 首包成功?, RX 收到数, 备注)"""
    hl = healthy(MODIP)
    if hl < 0:
        return ("LINK-BAD", False, 0, "ping 丢包>30%, 跳过")

    cleanup()
    cmd("AT+CIPMUX=%d" % mux, 4)
    cmd("AT+CIPMODE=%d" % mode, 4)

    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    u.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        u.bind(("", PCPORT))
    except Exception as e:
        u.close()
        return ("BINDERR", False, 0, str(e))
    u.settimeout(0.5)

    if mux == 1:
        line = 'AT+CIPSTART=0,"UDP","%s",%d,%d,0' % (PC_IP, PCPORT, lport)
    else:
        line = 'AT+CIPSTART="UDP","%s",%d,%d,0' % (PC_IP, PCPORT, lport)

    if mode == 1:
        a.clear()
        a.send(line=line)
        acc = pump_for(4)
        st = "NOERR" if "ERROR" not in acc else "ERROR"
    else:
        st, _ = cmd(line, 12)
        if st != "OK":
            u.close()
            return (st, False, 0, "建连失败")

    # ★ PC 先发一个热包: 1) 打开有状态防火墙的孔(否则模组非请自来的入站 UDP 被拦)
    #   2) 顺带让模组学到 PC 的 MAC, 排除 ARP 未解析
    for _ in range(3):
        u.sendto(b"warmup", (MODIP, lport))
        time.sleep(0.4)

    if mode == 1:
        # 进入透传
        _, acc2 = cmd("AT+CIPSEND", 5)
        entered = ">" in acc2
        if not entered:
            u.close()
            return (st, False, 0, "透传未进入(无 '>')")
    else:
        entered = True

    # 首包(重试最多 6 次)
    peer = None
    for _ in range(6):
        peer = send_first(u, mux, mode)
        if peer:
            break
    if not peer:
        u.close()
        if mode == 1:
            a.send(raw=b"+++")
            time.sleep(1.2)
            a.pump(0.5)
        return (st, False, 0, "PC 未收到首包")

    # RX 阶段
    a.clear()
    seen = len(re.findall(re.escape(PAYLOAD), a.buf))
    got = 0
    for _ in range(M):
        u.sendto(PAYLOAD, (peer[0], lport))
        t0 = time.time()
        while time.time() - t0 < 1.0:
            a.pump(0.1)
            now = len(re.findall(re.escape(PAYLOAD), a.buf))
            if now > seen:
                got += 1
                seen = now
                break
    peerstr = "%s:%d" % (peer[0], peer[1])
    u.close()
    if mode == 1:
        a.send(raw=b"+++")
        time.sleep(1.2)
        a.pump(0.5)
    return (st, True, got, "peer=%s" % peerstr)


CFG_A = ("mode0/mux1/lp1001", 1, 0, 1001)
CFG_B = ("mode1/mux0/lp2000", 0, 1, 2000)

rows = []
for r in range(1, ROUNDS + 1):
    for name, mux, mode, lport in (CFG_A, CFG_B):
        t0 = time.time()
        st, first, got, note = one_round(mux, mode, lport)
        rows.append((r, name, st, first, got, note, round(time.time() - t0, 1)))
        print("#%-2d %-18s st=%-7s first=%-5s RX=%d/%d  %s  (%.1fs)" %
              (r, name, st, "Y" if first else "N", got, M, note,
               time.time() - t0))

a.close()

print("\n== 汇总 ==")
for name in (CFG_A[0], CFG_B[0]):
    sub = [x for x in rows if x[1] == name]
    okr = sum(1 for x in sub if x[4] == M)
    anyr = sum(1 for x in sub if x[4] > 0)
    print("  %-18s RX 全通 %d/%d 轮, 有收 %d/%d 轮" %
          (name, okr, len(sub), anyr, len(sub)))
