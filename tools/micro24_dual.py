# -*- coding: utf-8 -*-
"""MICRO24: 双模组并发对照 —— 判定 #13 的丢包是否与外接环境同源。

COM5 与 COM6 同时连 MyHomeWiFi, 各自跑同一套 UDP echo 轮次(间隔同步),
逐轮记录是否收到。若两者的失败窗口高度重合 => 环境(AP/空口/干扰)导致;
若只有其中一个失败 => 该模组自身问题。
用法: python tools/micro24_dual.py [COM_A] [COM_B] [rounds]
"""
import sys, os, time, re, socket, threading
sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PC_IP = "192.168.0.152"
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)

COM_A = sys.argv[1] if len(sys.argv) > 1 else "COM5"
COM_B = sys.argv[2] if len(sys.argv) > 2 else "COM6"
NROUND = int(sys.argv[3]) if len(sys.argv) > 3 else 16

barrier = threading.Barrier(2, timeout=30)
results = {"A": [], "B": []}
lock = threading.Lock()


def run(tag, com, pcbase, lport):
    a = AT("MICRO24_" + tag, com, LOGDIR)

    def cmd(line, t=8):
        a.clear(); a.send(line=line)
        t0 = time.time(); acc = ""
        while time.time() - t0 < t:
            acc += a.pump(0.2)
            if re.search(r"OK\r?\n", acc):
                return "OK"
            if "ERROR" in acc:
                return "ERROR"
        return "TIMEOUT"

    def connect():
        cmd("ATE1", 4)
        cmd("AT+CWMODE=1", 6)
        cmd('AT+CWJAP="MyHomeWiFi","<WIFI_PWD>"', 25)
        t0 = time.time()
        while time.time() - t0 < 20:
            if "GOT IP" in a.pump(0.3):
                break
        time.sleep(2); a.clear()
        cmd("AT+CIPMUX=1", 6)

    def one(pcport, r):
        uc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        uc.bind(("", pcport)); uc.settimeout(0.25)
        cmd('AT+CIPSTART=1,"UDP","%s",%d,%d,0' % (PC_IP, pcport, lport))
        a.clear(); a.send(line="AT+CIPSEND=1,10")
        time.sleep(0.6); a.pump(0.3); a.clear(); a.send(raw=b"sparkleiot")
        t0 = time.time(); addr = None
        while time.time() - t0 < 3:
            try:
                _, addr = uc.recvfrom(2048); break
            except socket.timeout:
                pass
        got = 0
        if addr:
            payload = b"SparkleIOT"
            for _ in range(3):
                uc.sendto(payload, (addr[0], addr[1]))
                t0 = time.time()
                hit = False
                while time.time() - t0 < 1.2:
                    a.pump(0.15)
                    if re.search(rb"\+IPD,1,10", a.buf):
                        hit = True; break
                if hit:
                    got = 1; break
        uc.close()
        return got

    try:
        connect()
        barrier.wait()
        for r in range(1, NROUND + 1):
            t0 = time.time()
            got = one(pcbase + r, r)
            with lock:
                results[tag].append((r, got, round(time.time() - T0, 1)))
            cmd("AT+CIPCLOSE=5", 4)
            # 对齐节奏: 每轮固定 7s
            dt = 7.0 - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)
    finally:
        a.close()


T0 = time.time()
tA = threading.Thread(target=run, args=("A", COM_A, 50700, 1010))
tB = threading.Thread(target=run, args=("B", COM_B, 50800, 1010))
tA.start(); tB.start()
tA.join(); tB.join()

ra = {r: g for r, g, t in results["A"]}
rb = {r: g for r, g, t in results["B"]}
print("== 双模组并发 (A=%s B=%s) ==" % (COM_A, COM_B))
fa = fb = both = onlya = onlyb = 0
for i in range(1, NROUND + 1):
    ga, gb = ra.get(i), rb.get(i)
    mark = ""
    if ga == 0 and gb == 0:
        both += 1; mark = "  <== 同时失败"
    elif ga == 0:
        onlya += 1; mark = "  <== 仅 A 失败"
    elif gb == 0:
        onlyb += 1; mark = "  <== 仅 B 失败"
    print("  #%-3d A=%s B=%s%s" % (i, "收" if ga else "丢", "收" if gb else "丢", mark))
print("== 统计: 同时失败 %d 轮, 仅A %d 轮, 仅B %d 轮, 共 %d 轮 ==" % (both, onlya, onlyb, NROUND))
