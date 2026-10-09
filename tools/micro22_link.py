# -*- coding: utf-8 -*-
"""MICRO22: 判定 #13 是否 = 链路/省电导致的单播丢失。

全程后台 ping 模组 (ICMP 单播, 长超时 2000ms), 每轮做一次 UDP echo 测试,
统计该轮窗口内 ping 的丢包率与 RTT。

判据:
  * UDP 失败的轮次  <=>  ping 丢包率显著升高 / RTT 尖峰  => 链路问题(省电休眠),
     不是 UDP/AT 固件 bug
  * UDP 失败而 ping 全程 0 丢包低 RTT                    => UDP 专属固件问题
用法: python tools/micro22_link.py [COM5] [bind|zero]
"""
import sys, os, time, re, socket, subprocess, threading
sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PC_IP = "192.168.0.152"
MOD_IP = "192.168.0.163"
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
MODE = sys.argv[2] if len(sys.argv) > 2 else "bind"
LPORT = 1010 if MODE == "bind" else 0
PINGLOG = "test/micro22_ping.log"
RAW = open("test/micro22_%s_raw.log" % MODE, "wb")

a = AT("MICRO22", PORT, LOGDIR)

# ---- 后台 ping ----
ping_proc = None


def ping_start():
    global ping_proc
    with open(PINGLOG, "w", encoding="gbk", errors="replace") as f:
        f.write("")
    ping_proc = subprocess.Popen(
        ["ping", "-n", "2000", "-w", "2000", MOD_IP],
        stdout=open(PINGLOG, "a", encoding="gbk", errors="replace"),
        stderr=subprocess.STDOUT)


def ping_stop():
    if ping_proc:
        try:
            ping_proc.terminate()
        except Exception:
            pass


def ping_window(t0_size):
    """返回 (新增回复数, 新增超时数, rtt列表)"""
    try:
        txt = open(PINGLOG, encoding="gbk", errors="replace").read()
    except Exception:
        return 0, 0, []
    seg = txt[t0_size:]
    vias = re.findall(r"时间[=<](\d+)ms", seg)
    tos = seg.count("请求超时") + seg.count("Request timed out")
    rtts = [int(v) for v in vias]
    return len(rtts), tos, rtts


def ping_size():
    try:
        return len(open(PINGLOG, encoding="gbk", errors="replace").read())
    except Exception:
        return 0


def pump(dt=0.2):
    t = a.pump(dt)
    if t:
        RAW.write(t.encode("utf-8", "replace")); RAW.flush()
    return t


def cmd(line, t=8):
    a.clear(); a.send(line=line)
    t0 = time.time(); acc = ""
    while time.time() - t0 < t:
        acc += pump(0.2)
        if re.search(r"OK\r?\n", acc):
            return "OK", acc
        if "ERROR" in acc:
            return "ERROR", acc
    return "TIMEOUT", acc


def rssi():
    _, out = cmd("AT+CWJAP?", 6)
    RAW.write(("\n[CWJAP] " + out.replace("\r", "") + "\n").encode("utf-8", "replace"))
    RAW.flush()
    nums = re.findall(r"-\d+", out.split("+CWJAP:")[-1]) if "+CWJAP:" in out else []
    return nums[-1] if nums else "?"


def round_test(pcport, lport, tag):
    uc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    uc.bind(("", pcport)); uc.settimeout(0.25)
    cmd('AT+CIPSTART=1,"UDP","%s",%d,%d,0' % (PC_IP, pcport, lport))
    a.clear(); a.send(line="AT+CIPSEND=1,10")
    time.sleep(0.7); pump(0.3); a.clear(); a.send(raw=b"sparkleiot")
    t0 = time.time(); addr = None
    while time.time() - t0 < 3:
        try:
            _, addr = uc.recvfrom(2048); break
        except socket.timeout:
            pass
    got = sent = 0
    rtts = []
    okc = toc = 0
    if addr:
        psz = ping_size()
        payload = b"SparkleIOT"
        for _ in range(8):
            sent += 1
            uc.sendto(payload, (addr[0], addr[1]))
            t0 = time.time()
            hit = False
            while time.time() - t0 < 1.0:
                pump(0.15)
                if re.search(rb"\+IPD,1,10", a.buf):
                    hit = True; break
            if hit:
                got += 1
        okc, toc, rtts = ping_window(psz)
    rss = rssi()
    rtxt = ("%d-%dms" % (min(rtts), max(rtts))) if rtts else "-"
    tot = okc + toc
    loss = ("%.0f%%" % (100.0 * toc / tot)) if tot else "n/a"
    print("  [%-10s] udp=%d/%d | ping %d回/%d超时 丢=%s rtt=%s | rssi=%s" % (
        tag, got, sent, okc, toc, loss, rtxt, rss))
    uc.close()
    return got, sent


def connect():
    cmd("ATE1", 4)
    cmd("AT+CWMODE=1", 6)
    cmd('AT+CWJAP="MyHomeWiFi","<WIFI_PWD>"', 25)
    t0 = time.time()
    while time.time() - t0 < 20:
        if "GOT IP" in pump(0.3):
            break
    time.sleep(2); a.clear()
    cmd("AT+CIPMUX=1", 6)


try:
    connect()
    print("== micro22 MODE=%s LPORT=%d ==" % (MODE, LPORT))
    ping_start()
    time.sleep(2)
    for i in range(1, 13):
        round_test(50600 + i, LPORT, "%s#%d" % (MODE, i))
        cmd("AT+CIPCLOSE=5", 4); time.sleep(1.0)
    ping_stop()
    time.sleep(1)
    okc, toc, rtts = ping_window(0)
    print("== 全程 ping: %d 回 / %d 超时, rtt %s ==" % (
        okc, toc, ("%d-%dms" % (min(rtts), max(rtts))) if rtts else "-"))
    RAW.write(b"\n########## DONE ##########\n")
finally:
    ping_stop()
    RAW.close()
    a.close()
