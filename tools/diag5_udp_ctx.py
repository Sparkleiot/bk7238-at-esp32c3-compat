#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DIAG5: 定位 2.4/2.5 UDP 回发 +IPD 收不到的"前置状态依赖"。

背景:
- 独立复刻(干净 CWJAP 后)sec24 双 UDP 序列, PC 回发链路 1 一切正常 (+IPD,1,10)。
- 完整脚本里 sec24 位于 sec21/22/23 之后, 回发 100% 收不到 (x3 重试也无效),
  且 sec25 (单连接 UDP 透传)同样收不到 —— 但模块发包方向一切正常。
- 假设: 前置 section (最大嫌疑 sec23 TCP 透传)的残留状态毒化了 UDP 接收路径。

对照序列:
  A: 干净状态(重新 CWJAP) → sec24 精简 → 回发      预期成功(已知)
  B: sec23 精简(TCP 透传)   → sec24 精简 → 回发      看假设是否成立
  C: AT+RST 复位           → sec24 精简 → 回发      看复位能否救回
  D: AT+CIPMUX/CIPMODE 序列(无 TCP 透传)→ sec24 精简  收窄毒源
用法: python tools/diag5_udp_ctx.py [COM5]
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import at_doc_v15_test as T  # noqa: E402
from at_doc_v15_test import (AT, UDPHelper, TCPSrv, P11, P30, PC_IP,
                             ROUTER_SSID, ROUTER_PWD,
                             at_cmd, wait_str, wait_ipd, udp_start,
                             cipsend_fixed, enter_passthru_send, exit_passthru,
                             cleanup_links)  # noqa: E402


def udp_probe(a, tag):
    """sec24 精简序列, 返回回发是否收到 +IPD"""
    cleanup_links(a)
    at_cmd(a, "AT+CIPMUX=1", 6)
    bc = UDPHelper(50000)
    uc = UDPHelper(50001)
    st, q = at_cmd(a, "AT+CIFSR", 6)
    m = re.search(r'\+CIFSR:STAIP,"([\d.]+)"', q)
    mip = m.group(1) if m else "?"
    ok0, _ = udp_start(a, 'AT+CIPSTART=0,"UDP","255.255.255.255",50000,1000,0')
    s0, _ = cipsend_fixed(a, len(P11), P11, mux_id=0)
    d0 = bc.recv(6, 11)
    ok1, _ = udp_start(a, f'AT+CIPSTART=1,"UDP","{PC_IP}",50001,1001,0')
    s1, _ = cipsend_fixed(a, len(P11), P11, mux_id=1)
    d1 = uc.recv(6, 11)
    r = None
    peer = getattr(uc, "last_peer", None)
    if peer:
        for _ in range(3):
            uc.sendto(P30, (peer[0], 1001))
            r = wait_ipd(a, P30, 4)
            if r:
                break
    verdict = "OK 收到+IPD" if r else "FAIL 未收到"
    print(f"[{tag}] mip={mip} link0={ok0}/{s0}/{d0 == P11} "
          f"link1={ok1}/{s1}/{d1 == P11} peer={peer} => 回发: {verdict}")
    bc.close()
    uc.close()
    return r is not None


def sec23_probe(a):
    """sec23 精简: TCP 透传到 PC:8890, 收发 + +++ 退出"""
    cleanup_links(a)
    at_cmd(a, "AT+CIPMUX=0", 6)
    at_cmd(a, "AT+CIPMODE=1", 6)
    srv = TCPSrv(8890)
    st, acc = at_cmd(a, f'AT+CIPSTART="TCP","{PC_IP}",8890', 15)
    got = wait_str(a, r"CONNECT", 15)
    if got:
        srv.accept(8)
        enter_passthru_send(a, P11)
        srv.recv(6, 11)
        srv.sendall(P30)
        wait_str(a, re.escape(P30.decode()), 8)
        exit_passthru(a)
        at_cmd(a, "AT+CIPCLOSE", 6)
    at_cmd(a, "AT+CIPMODE=0", 6)
    srv.close()
    print(f"[sec23] TCP透传建连={'OK' if got else 'FAIL'}")
    return got is not None


def rst(a):
    at_cmd(a, "AT+RST", 6)
    time.sleep(6)
    a.pump(1.0)
    a.clear()


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
    logdir = os.path.join("test", "doc_v15_raw")
    os.makedirs(logdir, exist_ok=True)
    a = AT("DIAG5", port, logdir)
    res = {}
    try:
        # 复位到干净状态
        rst(a)
        at_cmd(a, "AT+CWMODE=1", 8)
        at_cmd(a, "ATE0", 4)
        st, acc = at_cmd(a, f'AT+CWJAP="{ROUTER_SSID}","{ROUTER_PWD}"', 25)
        got = wait_str(a, r"GOT IP", 20)
        print(f"[prep] CWJAP={'OK' if got else 'FAIL'}")

        res["A_干净"] = udp_probe(a, "A_干净")

        res["B_sec23后"] = sec23_probe(a) and udp_probe(a, "B_sec23后")

        if not res["B_sec23后"]:
            rst(a)
            at_cmd(a, "ATE0", 4)
            wait_str(a, r"GOT IP", 25)  # env 里已有 MyHomeWiFi, 复位后自动回连
            at_cmd(a, "AT+CWMODE=1", 6)
            res["C_RST后"] = udp_probe(a, "C_RST后")
    finally:
        a.close()
    print("\n==== DIAG5 结论 ====")
    for k, v in res.items():
        print(f"  {k}: {'收到+IPD' if v else '未收到'}")


if __name__ == "__main__":
    main()
