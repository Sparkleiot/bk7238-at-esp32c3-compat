#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DIAG6: 在 DIAG5(sec23 后 UDP RX 死)基础上收窄毒源。

变体(每个变体后立即 udp_probe):
  V0: 干净 → probe                    基线(应 OK)
  V1: TCP 普通模式 connect+send+close → probe   是不是任何 TCP 都毒?
  V2: CIPMODE=1→0(不建任何连接)       → probe   是不是透传标志残留?
  V3: TCP 透传完整(已知毒)            → probe   复现锚点(应 FAIL)
  V4: V3 毒化后, 检查 TCP RX 是否也死(+IPD)     UDP 特有还是全网 RX 死?
用法: python tools/diag6_udp_poison.py [COM5]
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
    cleanup_links(a)
    at_cmd(a, "AT+CIPMUX=1", 6)
    bc = UDPHelper(50000)
    uc = UDPHelper(50001)
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
    print(f"[{tag}] link1={ok1}/{s1}/{d1 == P11} peer={peer} => UDP回发: "
          f"{'OK' if r else 'FAIL'}")
    bc.close()
    uc.close()
    return r is not None


def tcp_plain(a):
    """V1: TCP 普通模式 connect + CIPSEND + close"""
    cleanup_links(a)
    at_cmd(a, "AT+CIPMUX=0", 6)
    srv = TCPSrv(8890)
    at_cmd(a, f'AT+CIPSTART="TCP","{PC_IP}",8890', 15)
    got = wait_str(a, r"CONNECT", 15)
    if got:
        srv.accept(8)
        cipsend_fixed(a, len(P11), P11)
        srv.recv(6, 11)
        srv.sendall(P30)
        wait_str(a, r"\+IPD,\d*:?36", 6)
        at_cmd(a, "AT+CIPCLOSE", 6)
    srv.close()
    print(f"[V1] TCP普通建连={'OK' if got else 'FAIL'}")
    return got is not None


def cipmode_toggle(a):
    """V2: 只拨 CIPMODE=1 → 0, 不建连接"""
    cleanup_links(a)
    at_cmd(a, "AT+CIPMUX=0", 6)
    at_cmd(a, "AT+CIPMODE=1", 6)
    time.sleep(1)
    at_cmd(a, "AT+CIPMODE=0", 6)
    print("[V2] CIPMODE 1→0 完成")


def tcp_passthru(a):
    """V3: TCP 透传完整(DIAG5 sec23 同款)"""
    cleanup_links(a)
    at_cmd(a, "AT+CIPMUX=0", 6)
    at_cmd(a, "AT+CIPMODE=1", 6)
    srv = TCPSrv(8890)
    at_cmd(a, f'AT+CIPSTART="TCP","{PC_IP}",8890', 15)
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
    print(f"[V3] TCP透传建连={'OK' if got else 'FAIL'}")
    return got is not None


def tcp_rx_check(a, tag):
    """V4: 毒化状态下 TCP RX 是否也死"""
    cleanup_links(a)
    at_cmd(a, "AT+CIPMUX=0", 6)
    srv = TCPSrv(8890)
    at_cmd(a, f'AT+CIPSTART="TCP","{PC_IP}",8890', 15)
    got = wait_str(a, r"CONNECT", 15)
    r = None
    if got:
        srv.accept(8)
        srv.sendall(P30)
        r = wait_str(a, r"\+IPD,\d*:?\d*", 6)
    at_cmd(a, "AT+CIPCLOSE", 6)
    srv.close()
    print(f"[{tag}] TCP建连={'OK' if got else 'FAIL'} TCP RX +IPD: "
          f"{'OK' if r else 'FAIL'}")
    return r is not None


def prep(a):
    at_cmd(a, "AT+RST", 6)
    time.sleep(6)
    a.pump(1.0)
    a.clear()
    at_cmd(a, "ATE0", 4)
    at_cmd(a, "AT+CWMODE=1", 8)
    at_cmd(a, f'AT+CWJAP="{ROUTER_SSID}","{ROUTER_PWD}"', 25)
    got = wait_str(a, r"GOT IP", 20)
    print(f"[prep] CWJAP={'OK' if got else 'FAIL'}")


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
    logdir = os.path.join("test", "doc_v15_raw")
    os.makedirs(logdir, exist_ok=True)
    a = AT("DIAG6", port, logdir)
    res = {}
    try:
        prep(a)
        res["V0_干净"] = udp_probe(a, "V0_干净")
        tcp_plain(a)
        res["V1_TCP后"] = udp_probe(a, "V1_TCP后")
        cipmode_toggle(a)
        res["V2_CIPMODE后"] = udp_probe(a, "V2_CIPMODE后")
        tcp_passthru(a)
        res["V3_透传后"] = udp_probe(a, "V3_透传后")
        if not res["V3_透传后"]:
            res["V4_透传后TCP_RX"] = tcp_rx_check(a, "V4_毒化TCP_RX")
    finally:
        a.close()
    print("\n==== DIAG6 结论 ====")
    for k, v in res.items():
        print(f"  {k}: {'OK' if v else 'FAIL/死'}")


if __name__ == "__main__":
    main()
