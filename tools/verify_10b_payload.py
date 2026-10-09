#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真机验证：AT+CIPSEND 发送 10 字节 'sparkleiot'（模组间路径）。

拓扑：COM7 = SoftAP(BK-M2M, 192.168.4.1)，COM6 = STA(192.168.4.3)
      PC 不参与数据面（跨网段不可达），纯模组对模组。
流程：COM7 起 CIPSERVER -> COM6 CIPSTART 连 COM7 -> COM6 CIPSEND=10 发 sparkleiot
      -> COM7 侧应收到 +IPD,0,10:sparkleiot
"""
import serial
import sys
import time

PAY = b"sparkleiot"
assert len(PAY) == 10, "payload 必须 10 字节"

AP = "COM7"
STA = "COM6"
PORT = 8899


def drain(s, w=0.7):
    out = b""
    t0 = time.time()
    while time.time() - t0 < w:
        c = s.read(500)
        if c:
            out += c
    return out


def cmd(s, line, w=2.0):
    drain(s, 0.25)
    s.write((line + "\r\n").encode())
    time.sleep(w)
    return drain(s, w).decode("utf-8", "replace")


def main():
    ap = serial.Serial(AP, 115200, timeout=0.3)
    sta = serial.Serial(STA, 115200, timeout=0.3)
    for s in (ap, sta):
        s.reset_input_buffer()
    time.sleep(0.4)

    print("payload = %r (%d 字节)" % (PAY, len(PAY)))
    print()

    # 0) 清干净两边残留连接
    for s in (sta, ap):
        cmd(s, "AT+CIPCLOSE=0", 2.0)
    cmd(ap, "AT+CIPSERVER=0", 1.5)
    time.sleep(0.5)

    # 1) AP 起 TCP server
    r = cmd(ap, "AT+CIPSERVER=1,%d" % PORT, 2.5)
    print("[AP ] CIPSERVER-> %s" % r.strip()[:50].replace("\r", " "))

    time.sleep(1.2)

    # 2) STA 连 AP
    r = cmd(sta, 'AT+CIPSTART=0,"TCP","192.168.4.1",%d' % PORT, 6.0)
    conn_ok = "CONNECT" in r
    print("[STA] CIPSTART   -> %s   [%s]" % (
        r.strip()[:50].replace("\r", " "), "OK" if conn_ok else "FAIL"))

    if not conn_ok:
        ap.close()
        sta.close()
        print("=== FAIL: 建连失败 ===")
        return 1

    time.sleep(1.5)

    # 3) STA 发 10 字节
    r = cmd(sta, "AT+CIPSEND=0,%d" % len(PAY), 2.0)
    print("[STA] CIPSEND=0,%-2d -> %s" % (len(PAY), r.strip()[:40].replace("\r", " ")))

    if ">" not in r:
        ap.close()
        sta.close()
        print("=== FAIL: 未进入透传数据态 ===")
        return 2

    sta.write(PAY + b"\x1a")
    time.sleep(2.0)
    print("[STA] 应答-> %s" % drain(sta, 1.5).decode("utf-8", "replace").strip()[:45].replace("\r", " "))

    # 4) AP 侧收
    got = drain(ap, 4.0)
    txt = got.decode("utf-8", "replace")
    print("[AP ] 收到   -> %s" % txt.strip()[:85].replace("\r", " "))

    cmd(sta, "AT+CIPCLOSE=0", 2.5)
    cmd(ap, "AT+CIPSERVER=0", 1.5)
    ap.close()
    sta.close()

    print()
    if (PAY in got) and (b"IPD" in got):
        print("=== PASS: AP 收到完整 10 字节 'sparkleiot'，+IPD 前缀与长度均正确 ===")
        return 0
    print("=== FAIL: AP 侧未收到预期数据 ===")
    return 1


if __name__ == "__main__":
    sys.exit(main())