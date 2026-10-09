#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MICRO5: 毒化状态下 ICMP/TCP/UDP 三元组 RX 判别。

 1. 基线 UDP client echo (link1, 1001)          → 应通
 2. 毒化: CIPCLOSE=5 → 2s → 重建 link1          → echo 应死
 3. 毒化状态三元组(顺序测):
    a. AT+PING="192.168.0.152"  (ICMP RX)
    b. TCP link2 建连 + PC 发 P30 → +IPD,2,10?   (TCP RX)
    c. UDP link1 echo 重试                        (UDP RX)
 4. AT+CIFSR / CIPSTATUS 确认状态
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import at_doc_v15_test as T  # noqa: E402
from at_doc_v15_test import (AT, UDPHelper, TCPSrv, P11, P30, PC_IP,
                             ROUTER_SSID, ROUTER_PWD,
                             at_cmd, wait_str, wait_ipd, cipsend_fixed,
                             cleanup_links)  # noqa: E402


def udp_echo(a, uc, linkid, lport, pcport, tag):
    at_cmd(a, "AT+CIPMUX=1", 6)
    st, _ = at_cmd(a, f'AT+CIPSTART={linkid},"UDP","{PC_IP}",{pcport},{lport},0', 12)
    ok, det = cipsend_fixed(a, len(P11), P11, mux_id=linkid)
    d = uc.recv(6, 11)
    peer = getattr(uc, "last_peer", None)
    r = None
    if peer:
        for _ in range(3):
            uc.sendto(P30, (peer[0], lport))
            r = wait_ipd(a, P30, 4)
            if r:
                break
    print(f"  [{tag}] 建连={st} 发送={'OK' if d == P11 else 'FAIL'}{peer} "
          f"echo={'收到' if r else '未收到'}")
    return r is not None


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
    logdir = "test/doc_v15_raw"
    os.makedirs(logdir, exist_ok=True)
    a = AT("MICRO5", port, logdir)
    try:
        print("== prep ==")
        at_cmd(a, "AT+RST", 6)
        time.sleep(6)
        a.pump(1.0)
        a.clear()
        at_cmd(a, "ATE0", 4)
        at_cmd(a, "AT+CWMODE=1", 8)
        at_cmd(a, f'AT+CWJAP="{ROUTER_SSID}","{ROUTER_PWD}"', 25)
        wait_str(a, r"GOT IP", 20)

        print("== 1. 基线 UDP echo ==")
        uc = UDPHelper(50001)
        udp_echo(a, uc, 1, 1001, 50001, "基线link1")

        print("== 2. 毒化 ==")
        cleanup_links(a)
        time.sleep(2)
        udp_echo(a, uc, 1, 1001, 50001, "毒化link1")

        print("== 3a. ICMP RX: AT+PING PC ==")
        st, acc = at_cmd(a, f'AT+PING="{PC_IP}"', 15)
        got = T.wait_str(a, r"\+PING:\d+", 8)
        print(f"  AT+PING => {st} {'+PING 有应答(ICMP RX 通)' if got else '无 +PING(ICMP RX 死)'}")

        print("== 3b. TCP RX (link2) ==")
        srv = TCPSrv(8891)
        at_cmd(a, "AT+CIPMUX=1", 6)
        st, _ = at_cmd(a, f'AT+CIPSTART=2,"TCP","{PC_IP}",8891', 15)
        got = wait_str(a, r"2,CONNECT|CONNECT", 15)
        tcp_rx = None
        if got:
            srv.accept(8)
            time.sleep(0.5)
            srv.sendall(P30)
            tcp_rx = wait_str(a, r"\+IPD,2,10", 8)
        print(f"  TCP 建连={'OK' if got else 'FAIL'} TCP RX: "
              f"{'收到 +IPD,2,10 (TCP RX 通)' if tcp_rx else '未收到'}")
        at_cmd(a, "AT+CIPCLOSE=2", 6)
        srv.close()

        print("== 3c. UDP RX 重试 ==")
        st, acc = at_cmd(a, "AT+CIPSTATUS", 8)
        d = uc.recv(3, 11)
        peer = getattr(uc, "last_peer", None)
        r = None
        if peer:
            for _ in range(3):
                uc.sendto(P30, (peer[0], 1001))
                r = wait_ipd(a, P30, 4)
                if r:
                    break
        print(f"  UDP echo 重试: {'收到' if r else '未收到'}")
        at_cmd(a, "AT+CIPCLOSE=5", 6)
        uc.close()
    finally:
        a.close()


if __name__ == "__main__":
    main()
