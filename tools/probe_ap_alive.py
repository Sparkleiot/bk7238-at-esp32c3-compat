#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""快速探测: SoftAP 是否在广播 beacon / 是否可被扫描定向命中"""
import time

import serial

sys_path = None
import sys, os
sys.path.insert(0, "tools")
from at_module_to_module_test import AT  # noqa: E402

AP_PORT = "COM7"
STA_PORT = "COM5"

apm = AT("APp", AP_PORT, "test/diag_raw")
stm = AT("STAp", STA_PORT, "test/diag_raw")

try:
    # 1. AP 侧状态
    ok, out = apm.cmd("AT+CWSAP?")
    print("AP CWSAP? :", out.strip())
    ok, out = apm.cmd("AT+CWLIF")
    print("AP CWLIF (关联列表):", out.strip() or "(空)")

    # 2. STA 定向扫描 BK-M2M
    stm.clear()
    stm.send(line='AT+CWLAP="BK-M2M"')
    res = stm.expect(r"\+CWLAP:|OK\r?\n|ERROR", timeout=25)
    stm.pump(2.0)
    txt = stm.buf.decode("utf-8", "replace")
    stm.buf = b""
    print("STA 定向扫描 BK-M2M:", repr(txt.strip()[:300]))

    # 3. 全扫描, 数一下 AP 总数
    stm.clear()
    stm.send(line="AT+CWLAP")
    t0 = time.time()
    n = 0
    while time.time() - t0 < 25:
        inc = stm.pump(0.5)
        n += inc.count("+CWLAP:")
        if "\r\nOK" in stm.buf.decode("utf-8", "replace"):
            break
    print(f"STA 全扫描: {n} 个 AP")

    # 4. AP 侧打开日志看 hostapd 活动(20 秒)
    apm.clear()
    apm.send(line="ATE1")
    time.sleep(1)
    print("--- AP 20s 日志(hostapd/beacon 活动) ---")
    txt = apm.pump(20)
    apm.buf = b""
    print(txt[-1500:] if txt.strip() else "(完全无日志 —— beacon/hostapd 无活动输出, 正常)")
    apm.send(line="ATE0")
    time.sleep(0.5)
    apm.buf = b""
finally:
    apm.close()
    stm.close()
