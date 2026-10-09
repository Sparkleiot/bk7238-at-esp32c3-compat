# -*- coding: utf-8 -*-
"""MICRO21: 判别 #13 到底是"空中接口丢单播"还是"UDP/固件特有"。

每轮: CIPSTART(bind 1010) -> CIPSEND -> 期间 PC 并发 ping 模组(单播 ICMP)
      -> 同时尝试收 UDP 回包 -> 记录 ping 丢包率 + UDP 是否收到 + RSSI + ARP 表。
判据:
  * UDP 失败 且 ping 也大量丢  => 空中接口/链路问题(高速率单播), 不是 UDP 专属固件 bug
  * UDP 失败 而 ping 0 丢包     => UDP/AT 层特有固件问题
用法: python tools/micro21_ping.py [COM5]
"""
import sys, os, time, re, socket, subprocess, threading
sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PC_IP = "192.168.0.152"
MOD_IP = "192.168.0.163"
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
RAW = open("test/micro21_raw.log", "wb")
a = AT("MICRO21", PORT, LOGDIR)


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
    if "+CWJAP:" not in out:
        return "?"
    tail = out.split("+CWJAP:")[-1]
    nums = re.findall(r"-?\d+", tail)
    return nums[-1] if nums else "?"


def _run(args, timeout):
    return subprocess.run(args, capture_output=True, timeout=timeout,
                          encoding="gbk", errors="replace").stdout or ""


def arp_entry():
    try:
        o = _run(["arp", "-a", MOD_IP], 5)
        for ln in o.splitlines():
            if MOD_IP in ln:
                return " ".join(ln.split())
    except Exception as e:
        return "arp-err:%s" % e
    return "no-entry"


def ping_stat(count=6, timeout_ms=1000):
    try:
        o = _run(["ping", "-n", str(count), "-w", str(timeout_ms), MOD_IP], count * timeout_ms / 1000 + 10)
        m = re.search(r"\((\d+)%", o)
        lost = 100 - int(m.group(1)) if m else -1
        m2 = re.search(r"(\d+)ms", o)
        return {"loss": lost, "avg": m2.group(0) if m2 else "?"}
    except Exception as e:
        return {"loss": -2, "avg": str(e)}


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
    payload = b"SparkleIOT"
    got, sent = 0, 0
    pinfo = {"loss": -1, "avg": "?"}
    arp = arp_entry()
    rs = rssi()
    if addr:
        res = {}
        th = threading.Thread(target=lambda: res.update(ping_stat()))
        th.start()
        for _ in range(8):
            sent += 1
            uc.sendto(payload, (addr[0], addr[1]))
            t0 = time.time()
            hit = False
            while time.time() - t0 < 0.9:
                pump(0.15)
                if re.search(rb"\+IPD,1,10", a.buf):
                    hit = True; break
            if hit:
                got += 1
        th.join()
        pinfo = res if res else pinfo
    print("  [%-10s] udp=%d/%d  ping丢=%s%% avg=%sms  rssi=%s  arp=%s" % (
        tag, got, sent, pinfo["loss"], pinfo["avg"], rs, arp))
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
    print("== micro21: udp vs ping vs rssi ==")
    for i in range(1, 11):
        round_test(50500 + i, 1010, "#%d" % i)
        RAW.write(("\n### round %d ###\n" % i).encode())
        cmd("AT+CIPCLOSE=5", 4); time.sleep(1.2)
    RAW.write(b"\n########## DONE ##########\n")
finally:
    RAW.close()
    a.close()
