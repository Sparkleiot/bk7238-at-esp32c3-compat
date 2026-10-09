# -*- coding: utf-8 -*-
"""MICRO10: 毒化窗口恢复曲线——制造毒化后每2秒回发一次, 测精确恢复时间。"""
import sys, os, time, re, socket
sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
PC_IP = "192.168.0.152"
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)
a = AT("MICRO10", PORT, LOGDIR)

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

    payload = u"probe".encode("utf-8")
    for rnd in range(2):
        print("== round %d ==" % (rnd + 1))
        uc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        uc.bind(("", 50080 + rnd)); uc.settimeout(0.3)
        # 基线
        cmd('AT+CIPSTART=1,"UDP","%s",%d,1001,0' % (PC_IP, 50080 + rnd))
        a.clear(); a.send(line="AT+CIPSEND=1,5"); time.sleep(0.6); a.pump(0.2); a.clear()
        a.send(raw=payload)
        addr = None
        t0 = time.time()
        while time.time() - t0 < 4:
            try:
                _, addr = uc.recvfrom(1024); break
            except socket.timeout:
                pass
        print("  基线 TX: %s" % ("OK" if addr else "FAIL"))
        # 毒化
        cmd("AT+CIPCLOSE=5", 4)
        tp = time.time()
        cmd('AT+CIPSTART=1,"UDP","%s",%d,1001,0' % (PC_IP, 50080 + rnd))
        a.clear(); a.send(line="AT+CIPSEND=1,5"); time.sleep(0.6); a.pump(0.2); a.clear()
        a.send(raw=payload)
        addr = None
        t0 = time.time()
        while time.time() - t0 < 4:
            try:
                _, addr = uc.recvfrom(1024); break
            except socket.timeout:
                pass
        if not addr:
            print("  毒化后 TX 也死了, 跳过 round"); uc.close(); continue
        # 每 2s 回发探测恢复
        while time.time() - tp < 60:
            el = time.time() - tp
            uc.sendto(payload, (addr[0], 1001))
            t0 = time.time(); ok = False
            while time.time() - t0 < 2.5:
                a.pump(0.2)
                if re.search(rb"\+IPD,1,5", a.buf):
                    ok = True; a.buf = b""; break
            if ok:
                print("  RX 恢复于 t+%.1fs" % el)
                break
        else:
            print("  60s 未恢复")
        cmd("AT+CIPCLOSE=5", 4)
        uc.close()
finally:
    a.close()
