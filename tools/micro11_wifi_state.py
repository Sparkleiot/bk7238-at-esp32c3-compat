# -*- coding: utf-8 -*-
"""MICRO11: 毒化窗口内判别 WiFi 关联状态 + 网络侧可达性。
COM5=被测(毒化), COM6=旁证(同 AP, ping COM5)。
"""
import sys, os, time, re, socket
sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PC_IP = "192.168.0.152"
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)
a = AT("MICRO11A", "COM5", LOGDIR)
b = AT("MICRO10B", "COM6", LOGDIR)

def cmd(x, line, t=8):
    x.clear(); x.send(line=line)
    t0 = time.time(); acc = ""
    while time.time() - t0 < t:
        acc += x.pump(0.2)
        if re.search(r"OK\r?\n", acc):
            return "OK", acc
        if "ERROR" in acc:
            return "ERROR", acc
    return "TIMEOUT", acc

def dump(x, line, t=8):
    x.clear(); x.send(line=line)
    t0 = time.time(); acc = ""
    while time.time() - t0 < t:
        acc += x.pump(0.2)
        if re.search(r"OK\r?\n|ERROR", acc):
            break
    time.sleep(0.3)
    acc += x.pump(0.3)
    return acc

def udp_echo(pcport, lport, tag):
    uc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    uc.bind(("", pcport)); uc.settimeout(0.3)
    st, _ = cmd(a, 'AT+CIPSTART=1,"UDP","%s",%d,%d,0' % (PC_IP, pcport, lport))
    a.clear(); a.send(line="AT+CIPSEND=1,10")
    time.sleep(0.8); a.pump(0.3); a.clear(); a.send(raw=b"sparkleiot")
    t0 = time.time(); addr = None
    while time.time() - t0 < 4:
        try:
            _, addr = uc.recvfrom(2048); break
        except socket.timeout:
            pass
    payload = b"SparkleIOT"
    r = None
    if addr:
        for _ in range(2):
            uc.sendto(payload, (addr[0], lport))
            t0 = time.time()
            while time.time() - t0 < 4:
                a.pump(0.2)
                if re.search(rb"\+IPD,1,10", a.buf):
                    r = True; break
            if r:
                break
    print("  [%s] 建连=%s echo=%s mip=%s" % (tag, st, u"收到" if r else u"未收到", addr[0] if addr else "?"))
    uc.close()
    return addr[0] if addr else None, r is not None

try:
    cmd(a, "ATE0", 4)
    cmd(a, "AT+CWMODE=1", 6)
    cmd(a, 'AT+CWJAP="MyHomeWiFi","<WIFI_PWD>"', 25)
    t0 = time.time()
    while time.time() - t0 < 20:
        if "GOT IP" in a.pump(0.3):
            break
    time.sleep(2); a.clear()
    cmd(a, "AT+CIPMUX=1", 6)
    # COM6 接入同 AP
    cmd(b, "ATE0", 4)
    cmd(b, "AT+CWMODE=1", 6)
    cmd(b, 'AT+CWJAP="MyHomeWiFi","<WIFI_PWD>"', 25)
    t0 = time.time()
    while time.time() - t0 < 20:
        if "GOT IP" in b.pump(0.3):
            break
    time.sleep(1); b.clear()
    mip6 = re.search(r"\+CIFSR:AIPSTA,\"([0-9.]+)\"", dump(b, "AT+CIFSR", 6))
    ip6 = mip6.group(1) if mip6 else None
    print("COM6 IP =", ip6)

    print("== 制造毒化 ==")
    mip, ok = udp_echo(50090, 1001, "基线link1")
    cmd(a, "AT+CIPCLOSE=5", 4); time.sleep(2)
    mip2, ok2 = udp_echo(50091, 1001, "毒化link1")
    print("== 毒化窗口: COM5 自查 ==")
    print("  CWJAP?: %r" % dump(a, "AT+CWJAP?", 6)[-120:].replace("\r", "").replace("\n", "|"))
    print("  CIPSTATUS: %r" % dump(a, "AT+CIPSTATUS", 6)[-80:].replace("\r", "").replace("\n", "|"))
    print("== 毒化窗口: COM6 -> COM5 ping ==")
    if mip:
        pb = dump(b, 'AT+PING="%s"' % mip, 14)
        got = re.findall(r"\+PING:[^\r\n]*", pb)
        print("  COM6 ping %s => %s" % (mip, "; ".join(got[:3]) if got else "无结果"))
    print("== 毒化窗口: COM5 -> COM6 ping ==")
    if ip6:
        pa = dump(a, 'AT+PING="%s"' % ip6, 14)
        got = re.findall(r"\+PING:[^\r\n]*", pa)
        print("  COM5 ping %s => %s" % (ip6, "; ".join(got[:3]) if got else "无结果"))
    cmd(a, "AT+CIPCLOSE=5", 4)
finally:
    a.close(); b.close()
