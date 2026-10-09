"""诊断 SoftAP 模组(COM7) 的 beacon 是否真的在空口广播。

用法: python tools/beacon_check.py --sta COM5
判据:
  - 扫到 BK-M2M        => beacon 正常，问题在关联/数据面
  - 扫不到但 AP 侧 OK  => beacon 停了（记忆里#9 的病症）
"""
import argparse
import re
import time

import serial


def one(s, cmd, wait):
    s.reset_input_buffer()
    s.write((cmd + "\r\n").encode())
    time.sleep(wait)
    return " ".join(s.read_all().decode("utf-8", "replace")
                    .replace("\r", "").replace("\n", " ").split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sta", default="COM5")
    ap.add_argument("--target", default="BK-M2M")
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()

    sta = serial.Serial(args.sta, 115200, timeout=1.0)
    sta.reset_input_buffer()
    sta.write(b"ATE0\r\n")
    time.sleep(2.0)
    sta.read_all()

    pat = re.compile(r'\+CWLAP:\((\d+),"([^"]*)",(-?\d+),"([0-9a-f:]+)"')
    for i in range(args.rounds):
        raw = one(sta, "AT+CWLAP", 14.0)
        found = pat.findall(raw)
        hit = [f for f in found if args.target in f[1]]
        print("[scan#%d] 共扫到 %d 个 AP; %s 命中 %d 个"
              % (i + 1, len(found), args.target, len(hit)))
        for mode, ssid, rssi, bssid in found[:8]:
            mark = " <<< 目标" if args.target in ssid else ""
            print("    type=%s ssid=%-16s rssi=%-5s bssid=%s%s"
                  % (mode, ssid, rssi, bssid, mark))
        print("  => beacon %s" % ("正常广播 ✓" if hit else "未广播 ✗"))
        if i + 1 < args.rounds:
            time.sleep(3)

    sta.close()


if __name__ == "__main__":
    main()