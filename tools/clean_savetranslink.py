# -*- coding: utf-8 -*-
"""CLEAN: 清掉 COM5 flash env 里的 SAVETRANSLINK 残留后重跑 UDP 毒化测试。
假设: sec31 写入的 AT+SAVETRANSLINK=1 (192.168.6.110:1002) 残留,
每次 GOT IP 固件自动发起幽灵连接并设 PASSTHROUGH -> UDP RX 死。
"""
import sys, os, time, re, socket
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from at_module_to_module_test import AT
import at_doc_v15_test as T

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)
a = AT("CLEAN", PORT, LOGDIR)

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

def udp_echo(lport, pcport, tag):
    uc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    uc.bind(("", pcport)); uc.settimeout(0.3)
    st, _ = cmd('AT+CIPSTART=1,"UDP","192.168.0.152",%d,%d,0' % (pcport, lport))
    a.clear(); a.send(line="AT+CIPSEND=1,10")
    time.sleep(0.6); a.pump(0.2); a.clear(); a.send(raw=b"sparkleiot")
    t0 = time.time(); got = b""
    while time.time() - t0 < 5:
        try:
            got, addr = uc.recvfrom(2048); break
        except socket.timeout:
            pass
    if not got:
        print("  [%s] TX FAIL" % tag); uc.close(); return False
    r = None
    payload = b"SparkleIOT"
    payload_s = payload.decode()
    for _ in range(3):
        uc.sendto(payload, (addr[0], lport))
        t0 = time.time()
        while time.time() - t0 < 4:
            inc = a.pump(0.2)
            if payload in inc or re.search(rb"\+IPD,1,10", a.buf):
                r = inc; break
            try:
                if payload_s in a.buf.decode("utf-8", "replace"):
                    r = a.buf.decode("utf-8", "replace"); break
            except Exception:
                pass
        if r:
            break
    print("  [%s] 建连=%s TX=OK echo=%s" % (tag, st, u"收到" if r else u"未收到"))
    uc.close()
    return r is not None

try:
    print("== 清 SAVETRANSLINK 残留 ==")
    cmd("ATE1", 4)
    st, acc = cmd("AT+SAVETRANSLINK=0", 6)
    print("  SAVETRANSLINK=0 => %s %r" % (st, acc[-40:]))
    st, acc = cmd("AT+SAVETRANSLINK?", 6)
    print("  查询 => %r" % (acc[-60:],))
    cmd("AT+RST", 6); time.sleep(6); a.pump(1.0); a.clear()
    cmd("ATE1", 4)
    cmd("AT+CWMODE=1", 6)
    cmd('AT+CWJAP="MyHomeWiFi","<WIFI_PWD>"', 25)
    T.wait_str(a, r"GOT IP", 20)
    time.sleep(3)
    drained = a.pump(1.0)
    print("  GOT IP 后 3s 串口输出(查幽灵连接): %r" % (drained[-200:],))
    a.clear()
    cmd("AT+CIPMUX=1", 6)
    print("== 毒化测试(无幽灵) ==")
    ok1 = udp_echo(1001, 50030, "基线link1")
    cmd("AT+CIPCLOSE=5", 4); time.sleep(2)
    ok2 = udp_echo(1001, 50031, "毒化link1")
    cmd("AT+CIPCLOSE=5", 4)
    print("结论: 基线=%s 毒化=%s" % (u"通" if ok1 else u"死", u"通" if ok2 else u"死"))
finally:
    a.close()
