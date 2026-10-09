# -*- coding: utf-8 -*-
"""MICRO26: 量化 CIPCLOSE -> CIPSTART 的本地端口释放窗口。

假设: network_stop_thread() 只清 threadrunflag 就立刻回 OK; 接收线程最多还要
      ~1s(select 超时)+200ms 才退出并 close(fd)。若上位机在 OK 后立刻用同一
      local port CIPSTART, bind() 撞上未释放的旧 socket => EADDRINUSE(98)
      => HAL_UDP_ConnectBind 返回 0 => netconnect 失败 => CIPSTART 回 ERROR。

做法: 对每个延迟 d(0.0 ~ 2.0s) 重复若干次:
        CIPSTART(lport=LPORT) 必须 OK (否则先 settle 重来)
        CIPCLOSE=5 (回 OK)
        sleep(d)
        CIPSTART(lport=LPORT) -> 记录 OK / ERROR
        CIPCLOSE=5 ; sleep(2.0) 复位
必须 ATE1 才能看到 ATSVRLOG(bind 失败 errno)。

用法: python tools/micro26_closebind.py [COM5] [LPORT]
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from at_module_to_module_test import AT

PC_IP = "192.168.0.152"
SSID = "MyHomeWiFi"
PWD = os.environ.get("BK7238_WIFI_PWD", "<WIFI_PWD>")
LOGDIR = "test/doc_v15_raw"
os.makedirs(LOGDIR, exist_ok=True)

COM = sys.argv[1] if len(sys.argv) > 1 else "COM5"
LPORT = int(sys.argv[2]) if len(sys.argv) > 2 else 1010
PCPORT = 50900
DELAYS = [0.0, 0.1, 0.3, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0]
REPS = 3

a = AT("MICRO26", COM, LOGDIR)


def cmd(line, t=10):
    a.clear()
    a.send(line=line)
    acc = ""
    t0 = time.time()
    while time.time() - t0 < t:
        acc += a.pump(0.15)
        if re.search(r"OK\r?\n", acc):
            return "OK", acc
        if "ERROR" in acc:
            return "ERROR", acc
    return "TIMEOUT", acc


CMD = 'AT+CIPSTART=1,"UDP","%s",%d,%d,0' % (PC_IP, PCPORT, LPORT)

cmd("ATE1", 2)          # 打开 bk_printf(ATSVRLOG)
cmd("AT+CWMODE=1", 6)
cmd('AT+CWJAP="%s","%s"' % (SSID, PWD), 25)
t0 = time.time()
while time.time() - t0 < 25:
    if "GOT IP" in a.pump(0.3):
        break
time.sleep(2)
a.clear()
cmd("AT+CIPMUX=1", 6)
print("模组已关联, 开始 CIPCLOSE->CIPSTART 释放窗口测量 (lport=%d)" % LPORT)

results = {}
for d in DELAYS:
    oks = 0
    errs = 0
    samples = []
    for rep in range(REPS):
        st, _ = cmd('AT+CIPSTART=1,"UDP","%s",%d,%d,0' % (PC_IP, PCPORT, LPORT), 10)
        if st != "OK":
            cmd("AT+CIPCLOSE=5", 5)
            time.sleep(2.5)
            st, _ = cmd('AT+CIPSTART=1,"UDP","%s",%d,%d,0' % (PC_IP, PCPORT, LPORT), 10)
        if st != "OK":
            samples.append("pre-fail")
            cmd("AT+CIPCLOSE=5", 5)
            time.sleep(2.5)
            continue
        cmd("AT+CIPCLOSE=5", 5)
        time.sleep(d)
        st2, acc = cmd('AT+CIPSTART=1,"UDP","%s",%d,%d,0' % (PC_IP, PCPORT, LPORT), 10)
        if st2 == "OK":
            oks += 1
            samples.append("OK")
        else:
            errs += 1
            tag = "ERROR"
            if "errno:98" in acc or "bind" in acc:
                tag += "(bind98)"
            samples.append(tag)
        cmd("AT+CIPCLOSE=5", 5)
        time.sleep(2.0)
    results[d] = (oks, errs, samples)
    print("  delay=%.1fs -> OK %d / ERROR %d   %s" % (d, oks, errs, samples))

a.close()
print("\n== 结论: 释放窗口 = 最小的 '全部 OK' 延迟 ==")
for d in DELAYS:
    oks, errs, s = results[d]
    print("  %.1fs : %s" % (d, "全 OK" if errs == 0 else "%d/%d 失败" % (errs, oks + errs)))
