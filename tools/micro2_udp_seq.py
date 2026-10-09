#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MICRO2: 逐条仪器化验证 UDP 建连/回发/链路槽状态。

新鲜复位后:
 1. CIPSTART=0 广播  → 记录应答(OK/ERROR/原文)
 2. CIPSTART=1 单播  → 记录应答
 3. CIPSEND 0/1 + PC 收包 + last_peer
 4. 回发 P30 x3 + wait_ipd
 5. AT+CIPSTATUS / AT+CIPSTATE 看链路残留
 6. cleanup 后立即再 CIPSTART=1(测槽位清理竞态) → 应答 + CIPSTATE
 7. 透传 TCP(sec23) 后再 CIPSTART=1 → 应答 + CIPSTATE
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import at_doc_v15_test as T  # noqa: E402
from at_doc_v15_test import (AT, UDPHelper, TCPSrv, P11, P30, PC_IP,
                             ROUTER_SSID, ROUTER_PWD,
                             at_cmd, wait_str, wait_ipd, cipsend_fixed,
                             enter_passthru_send, exit_passthru, cleanup_links)  # noqa: E402
import re  # noqa: E402


def show(a, line, tmo=12):
    st, acc = at_cmd(a, line, tmo)
    txt = acc.strip().replace("\r\n", "⏎")[-90:]
    print(f"  {line[:52]:54s} => {st:8s} {txt}")
    return st


def cipstate(a):
    a.clear()
    a.send(line="AT+CIPSTATE")
    time.sleep(1.2)
    out = a.pump(0.5).strip()
    print("  CIPSTATE:", out.replace("\r\n", " ⏎ ")[:200])
    a.clear()


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
    logdir = "test/doc_v15_raw"
    os.makedirs(logdir, exist_ok=True)
    a = AT("MICRO2", port, logdir)
    try:
        print("== 复位+联网 ==")
        at_cmd(a, "AT+RST", 6)
        time.sleep(6)
        a.pump(1.0)
        a.clear()
        at_cmd(a, "ATE0", 4)
        at_cmd(a, "AT+CWMODE=1", 8)
        at_cmd(a, f'AT+CWJAP="{ROUTER_SSID}","{ROUTER_PWD}"', 25)
        wait_str(a, r"GOT IP", 20)

        print("== 干净状态: 建连/回发 ==")
        at_cmd(a, "AT+CIPMUX=1", 6)
        bc = UDPHelper(50000)
        uc = UDPHelper(50001)
        show(a, 'AT+CIPSTART=0,"UDP","255.255.255.255",50000,1000,0')
        show(a, 'AT+CIPSTART=1,"UDP","192.168.0.152",50001,1001,0')
        cipsend_fixed(a, len(P11), P11, mux_id=0)
        d0 = bc.recv(6, 11)
        print(f"  PC 广播口收到: {d0!r}")
        cipsend_fixed(a, len(P11), P11, mux_id=1)
        d1 = uc.recv(6, 11)
        print(f"  PC 单播口收到: {d1!r} last_peer={getattr(uc, 'last_peer', None)}")
        r = None
        if getattr(uc, "last_peer", None):
            for _ in range(3):
                uc.sendto(P30, (uc.last_peer[0], 1001))
                r = wait_ipd(a, P30, 4)
                if r:
                    break
        print(f"  回发 +IPD: {'收到' if r else '未收到'}")
        cipstate(a)

        print("== cleanup 后立即再建(槽位竞态) ==")
        cleanup_links(a)
        show(a, 'AT+CIPSTART=1,"UDP","192.168.0.152",50001,1001,0')
        cipstate(a)
        show(a, "AT+CIPCLOSE=5", 4)
        time.sleep(2)
        show(a, 'AT+CIPSTART=1,"UDP","192.168.0.152",50001,1001,0')
        cipsend_fixed(a, len(P11), P11, mux_id=1)
        uc2 = UDPHelper(50002)
        d1 = uc.recv(6, 11)
        print(f"  PC 单播口收到: {d1!r} last_peer={getattr(uc, 'last_peer', None)}")
        if getattr(uc, "last_peer", None):
            for _ in range(3):
                uc.sendto(P30, (uc.last_peer[0], 1001))
                r = wait_ipd(a, P30, 4)
                if r:
                    break
        print(f"  回发 +IPD: {'收到' if r else '未收到'}")
        cleanup_links(a)
        bc.close()
        uc.close()
        uc2.close()

        print("== TCP 透传后 UDP 建连(毒化复测) ==")
        at_cmd(a, "AT+CIPMUX=0", 6)
        at_cmd(a, "AT+CIPMODE=1", 6)
        srv = TCPSrv(8890)
        at_cmd(a, f'AT+CIPSTART="TCP","{PC_IP}",8890', 15)
        wait_str(a, r"CONNECT", 15)
        srv.accept(8)
        enter_passthru_send(a, P11)
        srv.recv(6, 11)
        srv.sendall(P30)
        wait_str(a, re.escape(P30.decode()), 8)
        exit_passthru(a)
        at_cmd(a, "AT+CIPCLOSE", 6)
        at_cmd(a, "AT+CIPMODE=0", 6)
        srv.close()
        time.sleep(1.5)
        print("  -- TCP done, 建 UDP --")
        at_cmd(a, "AT+CIPMUX=1", 6)
        uc3 = UDPHelper(50003)
        show(a, 'AT+CIPSTART=1,"UDP","192.168.0.152",50003,2001,0')
        cipsend_fixed(a, len(P11), P11, mux_id=1)
        d1 = uc3.recv(6, 11)
        print(f"  PC 收到: {d1!r} last_peer={getattr(uc3, 'last_peer', None)}")
        r = None
        if getattr(uc3, "last_peer", None):
            for _ in range(3):
                uc3.sendto(P30, (uc3.last_peer[0], 2001))
                r = wait_ipd(a, P30, 4)
                if r:
                    break
        print(f"  回发 +IPD: {'收到' if r else '未收到'}")
        cipstate(a)
        cleanup_links(a)
        uc3.close()
    finally:
        a.close()


if __name__ == "__main__":
    main()
