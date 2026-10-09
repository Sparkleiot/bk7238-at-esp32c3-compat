# -*- coding: utf-8 -*-
"""MICRO8: ATE1(开日志)下复现 UDP 毒化, 抓 RXLOOP 探针。"""
import sys, os, time, re, socket
sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)
a = AT("MICRO8", PORT, LOGDIR)

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

def udp_echo(pcport, lport, tag):
    uc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    uc.bind(("", pcport)); uc.settimeout(0.3)
    st, _ = cmd('AT+CIPSTART=1,"UDP","192.168.0.152",%d,%d,0' % (pcport, lport))
    a.clear(); a.send(line="AT+CIPSEND=1,10")
    time.sleep(0.8); a.pump(0.3); a.clear(); a.send(raw=b"sparkleiot")
    t0 = time.time(); got = b""
    while time.time() - t0 < 5:
        try:
            got, addr = uc.recvfrom(2048); break
        except socket.timeout:
            pass
    payload = b"SparkleIOT"
    r = None
    for _ in range(2):
        uc.sendto(payload, (addr[0], lport))
        t0 = time.time()
        while time.time() - t0 < 4:
            a.pump(0.2)
            if re.search(rb"\+IPD,1,10", a.buf):
                r = a.buf.decode("utf-8", "replace"); break
        if r:
            break
    print("  [%s] 建连=%s echo=%s" % (tag, st, u"收到" if r else u"未收到"))
    uc.close()
    return r is not None

try:
    cmd("ATE1", 4)          # 打开日志, RXLOOP 才会出来
    cmd("AT+CWMODE=1", 6)
    st, _ = cmd('AT+CWJAP="MyHomeWiFi","<WIFI_PWD>"', 25)
    t0 = time.time()
    while time.time() - t0 < 20:
        if "GOT IP" in a.pump(0.3):
            break
    time.sleep(3); a.clear()
    cmd("AT+CIPMUX=1", 6)
    ok1 = udp_echo(50060, 1001, "基线")
    cmd("AT+CIPCLOSE=5", 4); time.sleep(2)
    ok2 = udp_echo(50061, 1001, "毒化重建")
    cmd("AT+CIPCLOSE=5", 4)
    print("结论: 基线=%s 毒化=%s" % (ok1, ok2))
finally:
    a.close()
