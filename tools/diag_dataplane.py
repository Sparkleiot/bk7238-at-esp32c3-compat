#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""二分诊断: RST 后逐步执行 m2m 测试流程里的每条命令, 每步之后测 AP 数据面
(ping 网关), 找出毒死数据面的具体命令。

用法: python tools/diag_dataplane.py [ap_port] [sta_port]
"""
import re
import sys
import time

import serial

sys.path.insert(0, "tools")
from at_module_to_module_test import AT, AP_SSID, AP_PWD  # noqa: E402

AP_PORT = sys.argv[1] if len(sys.argv) > 1 else "COM7"
STA_PORT = sys.argv[2] if len(sys.argv) > 2 else "COM5"


def rst(at, label, wait=16):
    at.clear()
    at.send(line="AT+RST")
    at.expect(r"ready|OK", timeout=8)
    time.sleep(wait)
    at.pump(0.5)
    at.buf = b""
    at.send(line="AT")
    ok = at.expect(r"\r?\nOK", timeout=6)
    at.buf = b""
    print(f"  RST {label}: {'alive' if ok else 'NO RESPONSE'}")
    return ok is not None


def ping_gateway(sta, gw="192.168.19.1"):
    """模块侧 ping, 返回 (ok, 摘要)"""
    sta.clear()
    sta.send(line=f'AT+PING="{gw}"')
    t0 = time.time()
    acc = ""
    while time.time() - t0 < 20:
        acc += sta.pump(0.3)
        if "+PING:" in acc:
            time.sleep(2)
            acc += sta.pump(1.0)
            break
        if "ERROR" in acc:
            return False, acc.strip()[:80]
    ok = bool(re.search(r"\+PING:\d+", acc)) or "time=" not in acc and "timeout" not in acc.lower()
    # 判定: 有 +PING:<ms> 数值即通
    ok = bool(re.search(r"\+PING:\s*\d+", acc))
    return ok, acc.strip()[-90:].replace("\n", " ⏎ ")


def join(sta, timeout=240):
    t_end = time.time() + timeout
    attempt = 0
    while time.time() < t_end:
        attempt += 1
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
                    return m.group(1), attempt
        time.sleep(2)
    return None, attempt


def step(name, fn=None, check=True):
    print(f"\n=== {name} ===")
    if fn:
        fn()
    if check:
        ok, det = ping_gateway(stm)
        print(f"  ping gw: {'通' if ok else '死'} | {det}")
        return ok
    return None


apm = AT("APd", AP_PORT, "test/diag_raw")
stm = AT("STAd", STA_PORT, "test/diag_raw")

try:
    print("== 基线: 双模组 RST ==")
    rst(apm, "AP")
    rst(stm, "STA")

    step("AP: ATE0 + 状态归零 (CIPMODE=0/CIPMUX=0)",
         lambda: (apm.cmd("ATE0"), time.sleep(0.4),
                  apm.cmd("AT+CIPMODE=0"), apm.cmd("AT+CIPMUX=0")), check=False)

    ip, tries = join(stm)
    print(f"  STA 关联: {'OK ip=' + str(ip) if ip else 'FAIL'} (第 {tries} 次)")
    if not ip:
        sys.exit("关联失败, 终止")

    alive = step("基线 ping (RST+关联后, 未跑任何其它命令)")
    if not alive:
        print("!!! 基线就死: RST 后直接关联仍毒死数据面 —— 与 sQtan0 矛盾, 记录现象")

    alive &= step("AP: AT+CWMODE=2 (期望 no-op)",
                  lambda: apm.cmd("AT+CWMODE=2"))

    alive &= step("AP: AT+CWSAP? 查询",
                  lambda: (apm.cmd("AT+CWSAP?"), apm.cmd("AT+CIPAP?")))

    alive &= step("AP: AT+CIPMUX=1",
                  lambda: apm.cmd("AT+CIPMUX=1"))

    alive &= step("AP: AT+CIPSERVER=1,8260",
                  lambda: apm.cmd("AT+CIPSERVER=1,8260", timeout=10))

    alive &= step("AP: AT+CIPSERVER=0",
                  lambda: apm.cmd("AT+CIPSERVER=0", timeout=10))

    alive &= step("AP: AT+CIPSERVER=1,8260 再开",
                  lambda: apm.cmd("AT+CIPSERVER=1,8260", timeout=10))

    # STA 侧命令对 AP 数据面影响
    alive &= step("STA: AT+CIPSTATUS?",
                  lambda: stm.cmd("AT+CIPSTATUS?"))

    print("\n== 结论 ==")
    print(f"当前数据面: {'活' if alive else '死'}")
    print("若中途某步后变死, 上一步打印的 'ping gw: 死' 即为毒化点")

finally:
    apm.close()
    stm.close()
