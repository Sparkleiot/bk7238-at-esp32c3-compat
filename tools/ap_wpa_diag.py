#!/usr/bin/env python3
"""BK7238 模组对模组 SoftAP 关联诊断。

干净流程: 双模组 RST -> AP 配 CWSAP(指定 ecn) -> 扫描确认 AP 在空口
         -> STA CWJAP -> 报告关联结果与 IP。
用于定位「open 能连 / WPA2 连不上」的根因。
"""
import sys
import time

import serial

AP_PORT = "COM6"
STA_PORT = "COM5"


class Mod:
    def __init__(self, port):
        self.ser = serial.Serial(port, 115200, timeout=0.1)
        time.sleep(0.3)
        self.ser.reset_input_buffer()

    def send(self, cmd):
        self.ser.reset_input_buffer()
        self.ser.write((cmd + "\r\n").encode())

    def pump(self, secs):
        buf = b""
        t0 = time.time()
        while time.time() - t0 < secs:
            n = self.ser.in_waiting
            if n:
                buf += self.ser.read(n)
            else:
                time.sleep(0.05)
        return buf.decode("utf-8", "replace").replace("\r", "")

    def cmd(self, line, wait=2.0):
        self.send(line)
        return self.pump(wait)

    def reset(self, wait=12):
        self.send("AT+RST")
        time.sleep(wait)
        self.ser.read(4000)

    def close(self):
        self.ser.close()


def wait_event(mod, pattern, timeout):
    """等一个异步事件(只从当前时刻起算)"""
    buf = ""
    t0 = time.time()
    low = pattern.lower()
    while time.time() - t0 < timeout:
        buf += mod.pump(0.2)
        if low in buf.lower():
            return True, buf
    return False, buf


def run(ap_ecn, ssid="BK-M2M", pwd="12345678"):
    print(f"\n{'='*62}")
    print(f"[诊断] AP ecn={ap_ecn}  SSID={ssid}  PWD={pwd!r}({len(pwd)}位)")
    print("=" * 62)

    ap = Mod(AP_PORT)
    sta = Mod(STA_PORT)
    try:
        print("[1] 双模组复位 ...")
        ap.reset()
        sta.reset()
        print("    复位完成")

        print("[2] AP: CWMODE=2 + CWSAP")
        print("   ", ap.cmd("AT+CWMODE=2", 2.0).strip().replace("\n", " | "))
        print("   ", ap.cmd(f'AT+CWSAP="{ssid}","{pwd}",1,{ap_ecn}', 3.0).strip().replace("\n", " | "))
        q = ap.cmd("AT+CWSAP?", 1.5)
        print("    CWSAP? ->", q.strip().replace("\n", " | "))
        time.sleep(4)

        print("[3] STA: 扫描确认 AP 在空口 (CWLAP)")
        sta.send(f'AT+CWLAP="{ssid}"')
        scan = sta.pump(12)
        found = ssid in scan
        print("    扫描:", "FOUND" if found else "NOT FOUND")
        for ln in scan.splitlines():
            if "CWLAP" in ln:
                print("   ", ln.strip())
        if not found:
            print("    !! AP 未广播, 后续关联无意义")
            return None

        print("[4] STA: CWJAP 关联")
        sta.send(f'AT+CWJAP="{ssid}","{pwd}"')
        joined = False
        t0 = time.time()
        buf = ""
        while time.time() - t0 < 25:
            buf += sta.pump(0.3)
            if "WIFI GOT IP" in buf:
                joined = True
                break
        print("    事件流:", buf.strip().replace("\n", " | ")[:300])
        print("    结果:", "CONNECTED ✅" if joined else "FAILED ❌")

        ip = sta.cmd("AT+CIFSR", 2.0)
        print("    CIFSR:", ip.strip().replace("\n", " | "))
        return joined
    finally:
        ap.close()
        sta.close()


if __name__ == "__main__":
    cases = [
        (0, "12345678"),   # open
        (3, "12345678"),   # WPA2_AES
        (4, "12345678"),   # WPA2_MIXED
    ]
    if len(sys.argv) > 1:
        cases = [(int(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "12345678")]
    results = []
    for ecn, pwd in cases:
        try:
            ok = run(ecn, pwd=pwd)
            results.append((ecn, pwd, ok))
        except Exception as e:  # noqa: BLE001
            print("   异常:", e)
            results.append((ecn, pwd, None))
    print(f"\n{'='*62}\n汇总: ecn=0(open)->{'PASS' if results[0][2] else 'FAIL'}")
    for ecn, pwd, ok in results:
        print(f"  ecn={ecn} pwd={pwd!r} -> {ok}")
