#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MICRO3: 判别 UDP RX 死亡的作用域。

 1. 基线: 新鲜 link1 (1001) echo → 应通
 2. 毒化: 关 link1, 等 2s, 重建 link1, echo → 应死(复现)
 3. ping 模组 (PC→模组 WiFi RX 是否还活着)
 4. 毒化状态下建 link0 (端口 3000, 全新端口) echo → link0 RX 通?
    → 通 = link1 专属槽坏; 死 = 全局 UDP 投递坏
 5. CIPSTATE 全链路快照
 6. AT+RST 后重建 link1 echo → 恢复?
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import at_doc_v15_test as T  # noqa: E402
from at_doc_v15_test import (AT, UDPHelper, P11, P30, PC_IP,
                             ROUTER_SSID, ROUTER_PWD,
                             at_cmd, wait_str, wait_ipd, cipsend_fixed,
                             cleanup_links)  # noqa: E402


def udp_echo(a, uc, linkid, lport, pcport, tag):
    st, _ = at_cmd(a, f'AT+CIPSTART={linkid},"UDP","{PC_IP}",{pcport},{lport},0', 12)
    ok, det = cipsend_fixed(a, len(P11), P11, mux_id=linkid if linkid else None)
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
    a = AT("MICRO3", port, logdir)
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
        at_cmd(a, "AT+CIPMUX=1", 6)
        mip = "192.168.0.163"

        print("== 1. 基线 link1 echo ==")
        uc1 = UDPHelper(50001)
        udp_echo(a, uc1, 1, 1001, 50001, "基线link1")

        print("== 2. 毒化: 关 link1 → 等2s → 重建 → echo ==")
        cleanup_links(a)
        time.sleep(2)
        uc1b = UDPHelper(50011)
        udp_echo(a, uc1b, 1, 1001, 50011, "毒化link1")

        print("== 3. ping 模组 ==")
        out = subprocess.run(["ping", "-n", "2", "-w", "1500", mip],
                             capture_output=True)
        txt = out.stdout.decode("gbk", "replace")
        tail = [ln for ln in txt.splitlines() if "TTL" in ln or "丢失" in ln]
        print("  ping:", " | ".join(tail[-2:]) if tail else txt[-120:].replace("\r\n", " "))

        print("== 4. 毒化状态下建全新 link0 (端口3000) echo ==")
        uc0 = UDPHelper(50010)
        udp_echo(a, uc0, 0, 3000, 50010, "毒化link0")

        print("== 5. CIPSTATE ==")
        a.clear()
        a.send(line="AT+CIPSTATE")
        time.sleep(1.2)
        print("  ", a.pump(0.5).strip().replace("\r\n", " ⏎ ")[:300])
        a.clear()

        print("== 6. RST 后重建 link1 echo ==")
        at_cmd(a, "AT+RST", 6)
        time.sleep(6)
        a.pump(1.0)
        a.clear()
        at_cmd(a, "ATE0", 4)
        wait_str(a, r"GOT IP", 25)
        at_cmd(a, "AT+CIPMUX=1", 6)
        uc1c = UDPHelper(50012)
        udp_echo(a, uc1c, 1, 1001, 50012, "RST后link1")

        cleanup_links(a)
        for u in (uc1, uc1b, uc0, uc1c):
            u.close()
    finally:
        a.close()


if __name__ == "__main__":
    main()
