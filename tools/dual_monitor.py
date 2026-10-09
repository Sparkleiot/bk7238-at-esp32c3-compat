#!/usr/bin/env python3
"""双串口同步抓取: STA 关联时同时监听 AP 侧 hostapd 接口输出。

用线程并行读两个串口, 打印带时间戳的日志, 便于对齐时序。
"""
import threading
import time

import serial

AP_PORT = "COM6"
STA_PORT = "COM5"
DURATION = 35.0


class Reader(threading.Thread):
    def __init__(self, port, tag):
        super().__init__(daemon=True)
        self.ser = serial.Serial(port, 115200, timeout=0.05)
        self.tag = tag
        self.log = []
        self.stop_flag = False

    def run(self):
        time.sleep(0.3)
        self.ser.reset_input_buffer()
        t_end = time.time() + DURATION
        while not self.stop_flag and time.time() < t_end:
            n = self.ser.in_waiting
            if n:
                data = self.ser.read(n)
                ts = time.time() - self.t0
                for line in data.decode("utf-8", "replace").replace("\r", "").split("\n"):
                    if line.strip():
                        self.log.append((ts, line.strip()))
            else:
                time.sleep(0.02)

    def write(self, s):
        self.ser.write(s.encode())

    def close(self):
        self.stop_flag = True
        self.ser.close()


def main():
    t0 = time.time()
    ap = Reader(AP_PORT, "AP")
    sta = Reader(STA_PORT, "STA")
    for r in (ap, sta):
        r.t0 = t0
    ap.start()
    sta.start()
    time.sleep(1.0)

    # 配置 AP 为 WPA2
    ap.write("AT+CWMODE=2\r\n")
    time.sleep(1.5)
    ap.write('AT+CWSAP="BK-M2M","12345678",1,3\r\n')
    time.sleep(4)

    # STA 关联
    sta.write('AT+CWJAP="BK-M2M","12345678"\r\n')

    time.sleep(DURATION - 8)
    ap.close()
    sta.close()
    ap.join(timeout=2)
    sta.join(timeout=2)

    merged = [(ts, tag, ln) for ts, ln in ap.log for tag in ["AP"]] + \
             [(ts, "STA", ln) for ts, ln in sta.log]
    merged.sort(key=lambda x: x[0])
    print("=== 同步时序日志 (t=秒) ===")
    for ts, tag, ln in merged:
        print(f"[{ts:6.2f}] {tag:3s} | {ln}")


if __name__ == "__main__":
    main()
