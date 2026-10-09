#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""上电恢复 SoftAP 崩溃(boot-loop)诊断 —— 抓带时间戳的启动日志。

背景: 若 env 里存了 CWMODE=2, `atsvr_poweron_default_action()` 的 SoftAP
分支会让 AT 任务卡住, 10s 后 CFG_INT_WDG(10000ms) 复位, 形成 boot-loop。
本脚本复位模块并抓取带时间戳的串口输出, 便于看探针卡在哪一步。

用法:
    python tools/pon_softap_diag.py COM7 --secs 16
"""
import argparse
import time

import serial


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('port')
    ap.add_argument('--secs', type=float, default=16.0)
    ap.add_argument('--baud', type=int, default=115200)
    args = ap.parse_args()

    s = serial.Serial(args.port, args.baud, timeout=0.05)
    s.dtr, s.rts = False, True
    time.sleep(0.15)
    s.dtr, s.rts = True, False
    time.sleep(0.15)
    s.dtr, s.rts = False, False
    time.sleep(0.1)
    s.reset_input_buffer()

    t0 = time.time()
    buf = b''
    while time.time() - t0 < args.secs:
        d = s.read(500)
        if not d:
            continue
        buf += d
        for ln in d.decode('utf-8', 'replace').splitlines():
            if ln.strip():
                print('%7.3f  %s' % (time.time() - t0, ln.rstrip()))
    s.close()
    print('--- total %d bytes, resets=%d ---'
          % (len(buf), buf.count(b'BK7238_1.0.14')))


if __name__ == '__main__':
    main()
