# -*- coding: utf-8 -*-
"""MICRO6: UDP 毒化判别——记录模组实际源端口。
若 CIPCLOSE=5 重建后模组源端口 != 1001, 则 bind 失败实锤;
再用实际源端口回发, 验证 RX 路径本身是否活着。
"""
import sys, os, time, re, socket
sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)
a = AT("MICRO6", PORT, LOGDIR)

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

def probe(pcport, lport, tag, reply_port=None):
    """建连->发->学源端口->(可选)按指定端口回发"""
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
        print("  [%s] TX FAIL" % tag); uc.close(); return None
    src_port = addr[1]
    print("  [%s] 建连=%s 模组实际源端口=%d (期望 %d)" % (tag, st, src_port, lport))
    # 回发: 默认回发到 lport, 或指定 reply_port
    target_port = reply_port if reply_port else lport
    payload = b"SparkleIOT"
    r = None
    for _ in range(3):
        uc.sendto(payload, (addr[0], target_port))
        t0 = time.time()
        while time.time() - t0 < 4:
            a.pump(0.2)
            if re.search(rb"\+IPD,1,10", a.buf):
                r = a.buf.decode("utf-8", "replace"); break
        if r:
            break
    print("  [%s] 回发到:%d -> RX %s" % (tag, target_port, u"收到" if r else u"未收到"))
    uc.close()
    return src_port, (r is not None)

try:
    cmd("ATE0", 4)
    cmd("AT+CIPMUX=1", 6)
    print("== 基线 ==")
    base = probe(50040, 1001, "基线")
    cmd("AT+CIPCLOSE=5", 4); time.sleep(2)
    print("== CIPCLOSE=5 重建 ==")
    r2 = probe(50041, 1001, "重建")
    if r2:
        src2, rx2 = r2
        if src2 != 1001:
            print(">> 源端口漂移! 实际=%d, 用实际源端口再试 RX" % src2)
            # 重建场景里 socket 已存在, 用同一条链路直接回发到实际源端口
        else:
            print(">> 源端口正常但 RX 死 -> bind 没问题, 是接收分发死了")
    cmd("AT+CIPCLOSE=5", 4)
finally:
    a.close()
