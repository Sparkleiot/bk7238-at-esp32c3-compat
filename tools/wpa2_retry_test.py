#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""BK7238 SoftAP(WPA2) <-> 本固件 STA 反复关联成功率测试。

为什么需要它
------------
AP 侧 / STA 侧的 wpa 日志与 AT 应答共用同一个 UART，
普通匹配("WIFI GOT IP")会被其它线程的日志字节打断
(实测出现过 "WIFI Gtemp_codOT Ie:...")，导致误判。
本脚本先把两块模组的日志关掉(ATE0)，再用 AT 查询回包做判定：

    AT+CWJAP?   -> "+CWJAP:" 已连 / "No AP" 未连
    AT+CIPSTA?  -> "+CIPSTA:ip:\"x.x.x.x\"" DHCP 成功
    AT+PING=... -> "+PING:<ms>" 三层可达

用法:
    python tools/wpa2_retry_test.py [次数] [ecn]
        ecn: 0=open 2=WPA_AES 3=WPA2_AES 4=WPA2_MIXED (默认 3)
"""
import re
import sys
import time

import serial

AP_PORT = "COM6"
STA_PORT = "COM5"
BAUD = 115200

SSID = "BK-M2M"
PWD = "12345678"
GW = "192.168.19.1"


class P:
    def __init__(self, name, port):
        self.name = name
        self.ser = serial.Serial(port, BAUD, timeout=0.05)
        self.buf = ""
        self.raw = []
        self.noise = 0

    def pump(self, dur=0.2):
        t0 = time.time()
        inc = b""
        while time.time() - t0 < dur:
            n = self.ser.in_waiting
            if n:
                d = self.ser.read(n)
                inc += d
            else:
                time.sleep(0.01)
        if inc:
            self.raw.append(inc)
        self.buf += inc.decode("utf-8", "replace")
        return inc

    def clear(self):
        self.pump(0.1)
        self.buf = ""

    def send(self, s):
        self.ser.write((s + "\r\n").encode())
        self.ser.flush()

    def wait(self, rx, timeout=10.0):
        r = re.compile(rx)
        t0 = time.time()
        while time.time() - t0 < timeout:
            self.pump(0.15)
            m = r.search(self.buf)
            if m:
                return m
        return None

    def noise_ratio(self, s):
        """统计不可打印字符比例，用于判断日志是否还在灌。"""
        if not s:
            return 0.0
        bad = sum(1 for c in s if not (32 <= ord(c) < 127 or c in "\r\n"))
        return bad / len(s)

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


def ascii_lines(text, keep=8):
    """从交织文本里挑出看起来完整的 ASCII 行。"""
    out = []
    for ln in text.replace("\r", "").split("\n"):
        ln = ln.strip()
        if len(ln) < 3:
            continue
        bad = sum(1 for c in ln if not (32 <= ord(c) < 127))
        if bad == 0:
            out.append(ln)
    return out[-keep:]


def main():
    global AP_PORT
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    ecn = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    if len(sys.argv) > 3:
        AP_PORT = sys.argv[3]

    print(f"[wpa2-retry] AP={AP_PORT} STA={STA_PORT} rounds={rounds} ecn={ecn}")
    ap = P("AP", AP_PORT)
    sta = P("STA", STA_PORT)
    results = []
    try:
        print("[0] ATE0 关闭两端日志，保证 AT 应答可被可靠匹配 ...")
        ap.send("ATE0")
        time.sleep(0.5)
        ap.clear()
        sta.send("ATE0")
        time.sleep(0.5)
        sta.clear()
        print("    静默确认 OK")

        print("[1] AT+RST 复位两块模组 ...")
        ap.send("AT+RST")
        sta.send("AT+RST")
        time.sleep(14)
        ap.clear()
        sta.clear()

        print(f"[2] AP: CWMODE=2 -> CWSAP(\"{SSID}\",1,{ecn}) ...")
        ap.send("AT+CWMODE=2")
        print("    CWMODE ->", "OK" if ap.wait(r"\bOK\b", 5) else "??")
        ap.send(f'AT+CWSAP="{SSID}","{PWD}",1,{ecn}')
        m = ap.wait(r"\bOK\b|\bERROR\b", 15)
        print("    CWSAP  ->", m.group(0) if m else "??")
        time.sleep(6)

        sta.send("AT+CWMODE=1")
        print("    STA CWMODE=1 ->", "OK" if sta.wait(r"\bOK\b", 5) else "??")
        sta.clear()

        for i in range(1, rounds + 1):
            print(f"\n===== 第 {i}/{rounds} 次 AT+CWJAP =====")
            sta.clear()
            t0 = time.time()
            sta.send(f'AT+CWJAP="{SSID}","{PWD}"')

            # 关联是异步的: 先 OK, 之后 WIFI CONNECTED / WIFI GOT IP
            # 注意 "WIFI GOT IP" 会被其它线程日志按字节打断, 这里只当"早退信号",
            # 真正的判定在后面的 AT 查询。
            ok = sta.wait(r"WIFI GOT IP", 60)
            dt = time.time() - t0
            raw = sta.buf
            evt = ("WIFI GOT IP" if ok else
                   ("WIFI DISCONNECT" if "WIFI DISCONNECT" in raw else "(超时)"))
            print(f"  [{dt:5.1f}s] 事件: {evt}")

            # ==== 权威判定: 用 AT 查询, 不看被打断的日志文本 ====
            sta.clear()
            sta.send("AT+CWJAP?")
            q = sta.wait(r"\+CWJAP:|No AP", 5)
            cwjap = q.group(0) if q else "??"
            line = ""
            if q and cwjap.startswith("+CWJAP:"):
                ln = sta.wait(r"\r\n", 1.0)
                line = (ln.string[ln.start():ln.start() + 90] if ln else "").strip()

            sta.clear()
            sta.send("AT+CIPSTA?")
            q2 = sta.wait(r"\+CIPSTA:ip:\"([^\"]+)\"", 5)
            ip = q2.group(1) if q2 else "(无)"

            ping = ""
            if ip and ip not in ("0.0.0.0", "(无)"):
                sta.clear()
                sta.send(f'AT+PING="{GW}"')
                q3 = sta.wait(r"\+PING:\d+|\+PING:TIMEOUT|\bERROR\b", 10)
                ping = q3.group(0) if q3 else "(超时)"

            verdict = "PASS" if (ip not in ("(无)", "0.0.0.0")) else "FAIL"
            print(f"  CWJAP?={cwjap}  {line}")
            print(f"  CIPSTA ip={ip}   PING({GW})={ping}   ==> {verdict}")
            results.append((i, dt, evt, cwjap, ip, ping, verdict))

            # 断开重连, 保证每轮都是冷启动
            sta.clear()
            sta.send("AT+CWQAP")
            sta.wait(r"\bOK\b", 5)
            time.sleep(3)

            # 顺便记录 AP 侧是否在反复 sta_add/sta_del
            ap.pump(0.2)
            adds = ap.buf.count("hapd_intf_sta_add")
            dels = ap.buf.count("hapd_intf_sta_del")
            if adds or dels:
                print(f"  [AP] 累计 sta_add={adds} sta_del={dels}")
                ap.buf = ""

        npass = sum(1 for r in results if r[6] == "PASS")
        print(f"\n================ 汇总: {npass}/{rounds} 成功 ================")
        for i, dt, evt, cwjap, ip, ping, v in results:
            print(f"  #{i} {v:4}  {dt:5.1f}s  ip={ip:<16} ping={ping}  evt={evt}")

        with open("test/wpa2_retry.md", "w", encoding="utf-8") as f:
            f.write("# WPA2 SoftAP 反复关联成功率\n\n")
            f.write(f"ecn={ecn} ssid={SSID} rounds={rounds} 成功 {npass}/{rounds}\n\n")
            f.write("| # | 耗时(s) | 事件 | CWJAP? | STA IP | PING | 判定 |\n")
            f.write("|---|--------|------|--------|--------|------|------|\n")
            for i, dt, evt, cwjap, ip, ping, v in results:
                f.write(f"| {i} | {dt:.1f} | {evt} | {cwjap} | {ip} | {ping} | {v} |\n")
        print("[wpa2-retry] 已写入 test/wpa2_retry.md")
    finally:
        ap.close()
        sta.close()


if __name__ == "__main__":
    main()
