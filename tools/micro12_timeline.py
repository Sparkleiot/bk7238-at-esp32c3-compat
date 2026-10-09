# -*- coding: utf-8 -*-
"""MICRO12: link1 常驻探针(500ms/个) + link0 建关循环。
精确定位: RX 死亡的触发点(建 or 关) 与 恢复耗时。
"""
import sys, os, time, re, socket
sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PC_IP = "192.168.0.152"
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)
a = AT("MICRO12", "COM5", LOGDIR)

def cmd(line, t=8):
    a.clear(); a.send(line=line)
    t0 = time.time(); acc = ""
    while time.time() - t0 < t:
        acc += a.pump(0.2)
        if re.search(r"OK\r?\n", acc):
            return "OK", acc
        if "ERROR" in acc:
            return "ERROR", acc
    return "TIMEOUT", acc

try:
    cmd("ATE0", 4)
    cmd("AT+CWMODE=1", 6)
    cmd('AT+CWJAP="MyHomeWiFi","<WIFI_PWD>"', 25)
    t0 = time.time()
    while time.time() - t0 < 20:
        if "GOT IP" in a.pump(0.3):
            break
    time.sleep(2); a.clear()
    cmd("AT+CIPMUX=1", 6)
    uc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    uc.bind(("", 50100)); uc.settimeout(0.05)

    cmd('AT+CIPSTART=1,"UDP","%s",50100,1001,0' % PC_IP)
    # link1 常驻: 先发一个 TX 学到模组地址
    a.clear(); a.send(line="AT+CIPSEND=1,1"); time.sleep(0.6); a.pump(0.2); a.clear()
    a.send(raw=b"P")
    addr = None
    t0 = time.time()
    while time.time() - t0 < 4:
        try:
            _, addr = uc.recvfrom(1024); break
        except socket.timeout:
            pass
    if not addr:
        print("link1 TX FAIL, abort"); raise SystemExit
    print("link1 就绪 mip=%s:%d" % addr)

    t_start = time.time()
    events = []          # (t, ipd_seen)
    ipd_count = 0
    last_ipd = 0
    def note(s):
        print("  t+%6.2fs %s" % (time.time() - t_start, s))

    # 阶段A: 基线 4s
    note("阶段A 基线 4s 开始")
    t_end = time.time() + 4
    while time.time() < t_end:
        uc.sendto(b"probe", (addr[0], 1001))
        inc = a.pump(0.1)
        for _ in range(3):
            a.pump(0.15)
        if re.search(rb"\+IPD,1,5", a.buf):
            ipd_count += 1; a.buf = b""
        time.sleep(0.4)
    note("阶段A结束 ipd=%d" % ipd_count)

    # 阶段B: 建 link0 -> 立即关 link0 (CIPCLOSE=0), 继续探针 25s
    a.buf = b""
    ipd_count = 0
    note("阶段B: 建 link0")
    cmd('AT+CIPSTART=0,"UDP","%s",50101,1002,0' % PC_IP)
    note("关 link0 (CIPCLOSE=0)")
    cmd("AT+CIPCLOSE=0", 4)
    t_end = time.time() + 25
    dead_from = None
    while time.time() < t_end:
        uc.sendto(b"probe", (addr[0], 1001))
        for _ in range(4):
            a.pump(0.12)
        if re.search(rb"\+IPD,1,5", a.buf):
            if dead_from is None:
                pass
            else:
                note("RX 恢复! (死了 %.1fs)" % (time.time() - dead_from))
                dead_from = None
            ipd_count += 1; a.buf = b""
        else:
            if dead_from is None:
                dead_from = time.time()
                note("RX 开始丢")
        time.sleep(0.3)
    if dead_from:
        note("到阶段B结束仍死 (%.1fs)" % (time.time() - dead_from))
    note("阶段B结束 ipd=%d" % ipd_count)

    # 阶段C: CIPCLOSE=5 (全关) -> 重建 link1 -> 探针 25s
    ipd_count = 0
    note("阶段C: CIPCLOSE=5 全关")
    cmd("AT+CIPCLOSE=5", 4)
    time.sleep(1)
    note("重建 link1")
    st, _ = cmd('AT+CIPSTART=1,"UDP","%s",50102,1001,0' % PC_IP)
    note("重建结果=%s" % st)
    a.clear(); a.send(line="AT+CIPSEND=1,1"); time.sleep(0.6); a.pump(0.2); a.clear()
    a.send(raw=b"P")
    addr2 = None
    t0 = time.time()
    while time.time() - t0 < 4:
        try:
            _, addr2 = uc.recvfrom(1024)
        except socket.timeout:
            pass
    note("重建后 TX: %s" % ("OK" if addr2 else "FAIL"))
    t_end = time.time() + 25
    dead_from = None
    while time.time() < t_end:
        uc.sendto(b"probe", (addr[0], 1001))
        for _ in range(4):
            a.pump(0.12)
        if re.search(rb"\+IPD,1,5", a.buf):
            if dead_from is not None:
                note("RX 恢复! (死了 %.1fs)" % (time.time() - dead_from))
                dead_from = None
            ipd_count += 1; a.buf = b""
        else:
            if dead_from is None:
                dead_from = time.time()
                note("RX 开始丢")
        time.sleep(0.3)
    if dead_from:
        note("到阶段C结束仍死 (%.1fs)" % (time.time() - dead_from))
    note("阶段C结束 ipd=%d" % ipd_count)
    cmd("AT+CIPCLOSE=5", 4)
finally:
    a.close()
