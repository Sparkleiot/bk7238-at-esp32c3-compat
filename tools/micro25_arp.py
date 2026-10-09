# -*- coding: utf-8 -*-
"""MICRO25: bug #13 决定性分离实验 —— 把"单播丢失"这一段拆开定位。

每轮流程 (在同一时间窗口内, 尽量原子):
  1. AT+CIPSTART=1,"UDP",<PC>,<pcport>,1010,0     (CIPCLOSE 历史照旧制造)
  2. AT+CIPSEND=1,10 + "sparkleiot"              (让 PC 学到模组的对端地址)
  3. 抓 PC 的 ARP 表项 (模组 IP -> MAC)            -> 排除 PC 侧 ARP 失效/串 MAC
  4. ping 模组 N 次 (ICMP 单播; ping 自己会解 ARP) -> 单播"能否到达模组 IP"
  5. PC -> 模组 UDP 单播 N 次 (到步骤 2 学到的端口) -> #13 的直接症状
  6. AT+CIPCLOSE=5

判读 (关键):
  * 步骤 4 通 + 步骤 5 丢  => 单播能进模组 IP, 丢在 UDP 端口投递/上层; 非空口/PS。
  * 步骤 4 丢 + 步骤 5 丢  => 单播整体进不来 => 空口/PS/ARP。
  * ARP MAC 与模组实际 MAC 不符 => PC 把单播发给了别的 MAC。

用法: python tools/micro25_arp.py [COM5] [rounds] [--lport 1010]
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
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)

COM = sys.argv[1] if len(sys.argv) > 1 else "COM5"
NROUND = int(sys.argv[2]) if len(sys.argv) > 2 else 20
LPORT = int(sys.argv[3]) if len(sys.argv) > 3 else 1010
PCPORT = 50900
PING_N = 4
UDP_N = 6


def sh(cmd):
    """Windows 命令输出是 GBK。"""
    try:
        return subprocess.run(cmd, shell=True, capture_output=True,
                              timeout=30).stdout.decode("gbk", "replace")
    except Exception as e:
        return "<err %s>" % e


def arp_mac(ip):
    out = sh("arp -a")
    for line in out.splitlines():
        if ip in line:
            parts = line.split()
            if len(parts) >= 2:
                return parts[1]
    return "(no-arp-entry)"


def ping_stat(ip, n=PING_N):
    out = sh("ping -n %d -w 2000 %s" % (n, ip))
    m = re.search(r"(\d+)\s*%", out)
    loss = int(m.group(1)) if m else -1
    return n - (n * loss // 100), loss


a = AT("MICRO25", COM, LOGDIR)


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


def q(line, t=3):
    a.clear()
    a.send(line=line)
    acc = ""
    t0 = time.time()
    while time.time() - t0 < t:
        acc += a.pump(0.2)
    return acc


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

ipout = q("AT+CIPSTA?", 4)
m = re.search(r'\+CIPSTA:ip:"([\d.]+)"', ipout)
MODIP = m.group(1) if m else None
print("模组 IP =", MODIP, " PC =", PC_IP, " lport =", LPORT,
      " rounds =", NROUND)
if not MODIP or MODIP == "0.0.0.0":
    print("!! 模组没拿到 IP, 终止")
    a.close()
    sys.exit(1)

cmd("AT+CIPMUX=1", 6)

rows = []
for r in range(1, NROUND + 1):
    t_round = time.time()
    uc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        uc.bind(("", PCPORT))
        uc.settimeout(0.25)
        st = cmd('AT+CIPSTART=1,"UDP","%s",%d,%d,0' % (PC_IP, PCPORT, LPORT))
        # --- 让 PC 学到模组的对端地址 ---
        a.clear()
        a.send(line="AT+CIPSEND=1,10")
        time.sleep(0.6)
        a.pump(0.3)
        a.clear()
        a.send(raw=b"sparkleiot")
        t0 = time.time()
        addr = None
        while time.time() - t0 < 3:
            try:
                _, addr = uc.recvfrom(2048)
                break
            except socket.timeout:
                pass
        if not addr:
            rows.append((r, st, "无回声", -1, -1, 0, "(none)", round(time.time() - t_round, 1)))
            cmd("AT+CIPCLOSE=5", 4)
            continue

        mac_before = arp_mac(MODIP)
        ps, loss = ping_stat(MODIP)
        mac_after = arp_mac(MODIP)

        # --- PC -> 模组 UDP 单播 ---
        # 注意: a.buf 是整个会话累积缓冲, 必须用"+IPD 出现次数"判断新增,
        # 否则第一包到达后每轮都会命中同一个旧缓冲 (假阳性)。
        got = 0
        payload = b"SparkleIOT"
        seen = len(re.findall(rb"\+IPD,1,10", a.buf))
        for _ in range(UDP_N):
            uc.sendto(payload, (addr[0], addr[1]))
            t0 = time.time()
            while time.time() - t0 < 1.0:
                a.pump(0.12)
                now = len(re.findall(rb"\+IPD,1,10", a.buf))
                if now > seen:
                    got += 1
                    seen = now
                    break
        rows.append((r, st, "有回声", ps, loss, got,
                     "%s/%s" % (mac_before, mac_after),
                     round(time.time() - t_round, 1)))
    finally:
        uc.close()
    cmd("AT+CIPCLOSE=5", 4)
    dt = 7.0 - (time.time() - t_round)
    if dt > 0:
        time.sleep(dt)

a.close()

print("\n轮   START  回波    ping(通/%d)   UDP单播(%d)   ARP(MAC)            用时" % (PING_N, UDP_N))
bad_udp = bad_ping = 0
for r, st, echo, ps, loss, got, mac, el in rows:
    flag = ""
    if got == 0 and ps > 0:
        flag = "  <== 单播 ping 通, UDP 全丢"
        bad_udp += 1
    elif got == 0 and ps == 0:
        flag = "  <== 单播整体不通"
        bad_udp += 1
        bad_ping += 1
    elif got < UDP_N:
        flag = "  <== UDP 部分丢"
    print("#%-3d %-6s %-6s %-11s %-13s %-19s %s%s" %
          (r, st, echo, ps, got, mac, el, flag))
print("\n== 汇总: UDP 全丢 %d 轮 / 单播整体不通 %d 轮 / 共 %d 轮 ==" %
      (bad_udp, bad_ping, NROUND))
