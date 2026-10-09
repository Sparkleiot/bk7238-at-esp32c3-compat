# -*- coding: utf-8 -*-
"""MICRO9: 毒化状态下的作用域判别。
a) ICMP RX: AT+PING PC
b) 全局/单socket: 毒化的 link1 之外, 新建 link0 UDP 能否收
"""
import sys, os, time, re, socket
sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
PC_IP = "192.168.0.152"
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)
a = AT("MICRO9", PORT, LOGDIR)

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

def udp_echo(linkid, pcport, lport, tag):
    uc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    uc.bind(("", pcport)); uc.settimeout(0.3)
    st, _ = cmd('AT+CIPSTART=%d,"UDP","%s",%d,%d,0' % (linkid, PC_IP, pcport, lport))
    a.clear(); a.send(line="AT+CIPSEND=%d,11" % linkid)
    time.sleep(0.8); a.pump(0.3); a.clear(); a.send(raw=b"sparkleiot")
    t0 = time.time(); got = b""
    while time.time() - t0 < 5:
        try:
            got, addr = uc.recvfrom(2048); break
        except socket.timeout:
            pass
    if not got:
        print("  [%s] TX FAIL" % tag); uc.close(); return False
    payload = b"SparkleIOT"
    r = None
    for _ in range(2):
        uc.sendto(payload, (addr[0], lport))
        t0 = time.time()
        while time.time() - t0 < 4:
            a.pump(0.2)
            if re.search(rb"\+IPD,%d,36" % linkid, a.buf):
                r = True; break
        if r:
            break
    print("  [%s] echo=%s" % (tag, u"收到" if r else u"未收到"))
    uc.close()
    return r is not None

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
    print("== 制造毒化 ==")
    udp_echo(1, 50070, 1001, "基线link1")
    cmd("AT+CIPCLOSE=5", 4); time.sleep(2)
    udp_echo(1, 50071, 1001, "毒化link1")
    print("== a) ICMP RX ==")
    a.clear(); a.send(line="AT+PING=\"%s\"" % PC_IP)
    t0 = time.time(); res = ""
    while time.time() - t0 < 12:
        res += a.pump(0.3)
        if re.search(r"\+PING:", res):
            pass
        if re.search(r"OK\r?\n", res) or re.search(r"ERROR", res):
            break
    got = re.findall(r"\+PING:[^\r\n]*", res)
    print("  AT+PING => %s" % ("; ".join(got[:3]) if got else "无结果"))
    print("== b) 新链路 link0 ==")
    udp_echo(0, 50072, 1002, "新link0")
    print("== c) 毒化 link1 再试(顺带) ==")
    udp_echo(1, 50073, 1001, "link1复测")
    cmd("AT+CIPCLOSE=5", 4)
finally:
    a.close()
