#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对照实验: 定位阶段3 透传建连 ERROR 的根因
A. CIPMODE=0 下 close/reopen 服务端后二次建连 -> 若失败 = 服务端循环问题
B. CIPMODE=1 下直接建连 -> 若失败 = CIPMODE=1 问题
C. 记录 ERROR 时延(立即=同步拒绝 / >3s=连接超时)
D. UDP 收发验证
"""
import sys
import time

sys.path.insert(0, "tools")
from at_module_to_module_test import AT, AP_SSID, AP_PWD  # noqa: E402

import re

AP_PORT = "COM7"
STA_PORT = "COM5"


def rst(at, wait=16):
    at.clear()
    at.send(line="AT+RST")
    at.expect(r"ready|OK", timeout=8)
    time.sleep(wait)
    at.pump(0.5)
    at.buf = b""
    at.send(line="AT")
    ok = at.expect(r"\r?\nOK", timeout=6)
    at.buf = b""
    return ok is not None


def join(sta, timeout=240):
    t_end = time.time() + timeout
    while time.time() < t_end:
        sta.clear()
        sta.send(line=f'AT+CWJAP="{AP_SSID}","{AP_PWD}"')
        sta.expect(r"\bOK\b", timeout=6)
        for _ in range(8):
            time.sleep(3)
            sta.clear()
            sta.send(line="AT+CIFSR")
            res = sta.expect(r'\+CIFSR:STAIP,"(\d+\.\d+\.\d+\.\d+)"', timeout=5)
            sta.pump(0.3)
            sta.buf = b""
            if res:
                m = re.search(r'(\d+\.\d+\.\d+\.\d+)"', res)
                if m and m.group(1) != "0.0.0.0":
                    return m.group(1)
        time.sleep(2)
    return None


def tcp_connect(sta, label, ap_ip="192.168.19.1", port=8260):
    """带计时: 返回 (结果, 耗时)"""
    sta.clear()
    t0 = time.time()
    sta.send(line=f'AT+CIPSTART="TCP","{ap_ip}",{port}')
    t = time.time() - t0
    res = sta.expect(r"CONNECT|\bERROR", timeout=15)
    if res and "CONNECT" in res:
        print(f"  [{label}] CONNECT  ({time.time()-t0:.1f}s)")
        return True
    print(f"  [{label}] {'ERROR after' if res else 'NO RSP after'} {time.time()-t0:.1f}s")
    return False


apm = AT("APx", AP_PORT, "test/diag_raw")
stm = AT("STAx", STA_PORT, "test/diag_raw")

try:
    print("RST...")
    assert rst(apm) and rst(stm)
    for at in (apm, stm):
        at.cmd("ATE0"); at.cmd("AT+CIPMODE=0"); at.cmd("AT+CIPMUX=0")
    ip = join(stm)
    print(f"关联: {ip}")
    assert ip

    # 服务端
    apm.cmd("AT+CIPMUX=1")
    ok, _ = apm.cmd("AT+CIPSERVER=1,8260", timeout=10)
    print(f"AP CIPSERVER=1: {ok}")

    # A1: 第一次建连 (CIPMODE=0)
    okA = tcp_connect(stm, "A1 第1次 CIPMODE=0")
    stm.cmd("AT+CIPCLOSE")
    apm.cmd("AT+CIPSERVER=0", timeout=10)
    time.sleep(1)
    ok, _ = apm.cmd("AT+CIPSERVER=1,8260", timeout=10)
    print(f"AP CIPSERVER 重开: {ok}")

    # A2: 第二次建连, 仍 CIPMODE=0 —— 区分: 服务端循环 vs CIPMODE
    okA2 = tcp_connect(stm, "A2 第2次 CIPMODE=0 (close/reopen 后)")
    if okA2:
        stm.cmd("AT+CIPCLOSE")

    # B: CIPMODE=1 后建连
    stm.cmd("AT+CIPMODE=1")
    okB = tcp_connect(stm, "B CIPMODE=1 建连")
    if okB:
        # B2: 透传收发
        stm.clear()
        stm.send(line="AT+CIPSEND")
        res = stm.expect(r">", timeout=5)
        print(f"  [B2] CIPSEND 提示符: {'OK' if res else '无'}")
        if res:
            stm.send(raw=b"PASSTHRU-TEST-123")
            ok, acc = apm.recv_payload("PASSTHRU-TEST-123", timeout=8)
            print(f"  [B2] AP 收到: {'YES' if ok else 'NO'}")
    stm.cmd("AT+CIPMODE=0")
    stm.cmd("AT+CIPCLOSE")

    # C: CIPMODE=1 但已有连接的重复 CIPSTART (同步拒绝路径)
    print("\n== C: 附加对照 ==")

    # D: UDP 往 AP 发 (验证阶段4 UDP 收不到问题)
    ok, _ = apm.cmd('AT+CIPSERVER=1,8261,"UDP"', timeout=10)
    print(f"AP UDP CIPSERVER=1,8261: {ok}")
    ok2, _ = stm.cmd('AT+CIPSTART="UDP","192.168.19.1",8261,8361,0', timeout=10)
    print(f"STA UDP CIPSTART: {ok2}")
    stm.clear()
    stm.send(line="AT+CIPSEND=12")
    stm.expect(r">", timeout=5)
    t0 = time.time()
    stm.send(raw=b"UDP-PROBE-01!")
    res = stm.expect(r"SEND OK|SEND ERROR", timeout=8)
    print(f"STA UDP SEND: {res if res else '无'} ({time.time()-t0:.1f}s)")
    ok, acc = apm.recv_payload("UDP-PROBE-01!", timeout=8)
    print(f"AP 收到 UDP: {'YES' if ok else 'NO'} | {acc.strip()[-50:]!r}")

    # E: TCP 建连还活着吗 (最后核对)
    okE = tcp_connect(stm, "E 最后 TCP 复核")

    print("\n== 结论 ==")
    print(f"A2 (close/reopen 二连): {'通' if okA2 else '死'}")
    print(f"B  (CIPMODE=1 建连):    {'通' if okB else '死'}")
    print(f"E  (最后 TCP):          {'通' if okE else '死'}")
finally:
    apm.close()
    stm.close()
