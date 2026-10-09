# -*- coding: utf-8 -*-
"""MICRO7: 用合法参数形式 AT+SAVETRANSLINK=0,0,0 清掉幽灵配置后重跑毒化测试。
若毒化消失 -> #14(单参清除不可达) 即根因确认。
"""
import sys, os, time, re, socket
sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)
a = AT("MICRO7", PORT, LOGDIR)

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
    time.sleep(0.6); a.pump(0.2); a.clear(); a.send(raw=b"sparkleiot")
    t0 = time.time(); got = b""; addr = None
    while time.time() - t0 < 5:
        try:
            got, addr = uc.recvfrom(2048); break
        except socket.timeout:
            pass
    if not got:
        print("  [%s] TX FAIL" % tag); uc.close(); return False
    print("  [%s] 建连=%s 源端口=%d" % (tag, st, addr[1]))
    payload = b"SparkleIOT"
    r = None
    for _ in range(3):
        uc.sendto(payload, (addr[0], lport))
        t0 = time.time()
        while time.time() - t0 < 4:
            a.pump(0.2)
            if re.search(rb"\+IPD,1,10", a.buf):
                r = a.buf.decode("utf-8", "replace"); break
        if r:
            break
    print("  [%s] RX %s" % (tag, u"收到" if r else u"未收到"))
    uc.close()
    return r is not None

try:
    cmd("ATE0", 4)
    print("== 清幽灵(4参数合法形式) ==")
    st, acc = cmd("AT+SAVETRANSLINK=0,0,0", 6)
    print("  SAVETRANSLINK=0,0,0 => %s %r" % (st, acc[-30:]))
    cmd("AT+RST", 6); time.sleep(6); a.pump(1.0); a.clear()
    cmd("ATE0", 4)
    cmd("AT+CWMODE=1", 6)
    st, _ = cmd('AT+CWJAP="MyHomeWiFi","<WIFI_PWD>"', 25)
    t0 = time.time()
    while time.time() - t0 < 20:
        if "GOT IP" in a.pump(0.3):
            break
    time.sleep(5)   # 等幽灵原本该触发的窗口过去
    drained = a.pump(1.0)
    print("  GOT IP 后 5s 串口输出(应为空): %r" % (drained[-120:],))
    a.clear()
    cmd("AT+CIPMUX=1", 6)
    print("== 毒化测试 ==")
    ok1 = udp_echo(50050, 1001, "基线")
    cmd("AT+CIPCLOSE=5", 4); time.sleep(2)
    ok2 = udp_echo(50051, 1001, "CIPCLOSE重建")
    cmd("AT+CIPCLOSE=5", 4); time.sleep(2)
    ok3 = udp_echo(50052, 1001, "二次重建")
    cmd("AT+CIPCLOSE=5", 4)
    print("结论: 基线=%s 重建1=%s 重建2=%s" % (ok1, ok2, ok3))
finally:
    a.close()
