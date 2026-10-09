"""RF 链路质量诊断：STA<->AP 反复 ping + 多次 TCP 建连，区分"固件问题"与"RF 抖动"。

用法: python tools/rf_quality_probe.py --sta COM5 --ap COM7
判据: ping 全通但 TCP 握手时通时不通 => RF 抖动（环境），不是固件回归。
"""
import argparse
import re
import time

import serial


def open_at(port, log_echo=False):
    s = serial.Serial(port, 115200, timeout=1.0)
    s.reset_input_buffer()
    s.write(("ATE1\r\n" if log_echo else "ATE0\r\n").encode())
    time.sleep(2.0)
    s.read_all()
    return s


def one(s, cmd, wait=6.0):
    """单条命令，读完再发下一条 —— 遵守项目铁律：不并发探测。"""
    s.reset_input_buffer()
    s.write((cmd + "\r\n").encode())
    time.sleep(wait)
    raw = s.read_all().decode("utf-8", "replace")
    return " ".join(raw.replace("\r", "").replace("\n", " ").split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sta", default="COM5")
    ap.add_argument("--ap", default="COM7")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--rounds", type=int, default=6)
    args = ap.parse_args()

    sta = open_at(args.sta)
    apm = open_at(args.ap)

    # ---- 1. RF 基线：反复 ping AP ----
    j = one(sta, "AT+CWJAP?", 5.0)
    m = re.search(r'\+CWJAP:"([^"]+)".*?,-(\d+),', j)
    if m:
        print("[RF] STA 已关联 %s  RSSI=%s dBm" % (m.group(1), m.group(2)))
    # 注意: STA 的 CIPSTA 返回的是**本机**地址(自 ping 恒通, 无诊断价值),
    # 必须从 AP 侧用 CIPAP/CIPAP? 取 AP 自己的 IP。
    ipm = re.search(r'ip:"([0-9.]+)"', one(apm, "AT+CIPAP?", 4.0))
    ap_ip = ipm.group(1) if ipm else "192.168.4.1"
    print("[RF] AP 侧地址 = %s" % ap_ip)

    print("[RF] ping %s x%d （自研 ICMP）" % (ap_ip, args.rounds))
    rtts = []
    for i in range(args.rounds):
        r = one(sta, 'AT+PING="%s"' % ap_ip, 4.0)
        mm = re.search(r"\+PING:(\d+)", r)
        if mm:
            rtts.append(int(mm.group(1)))
        print("   ping#%d %s" % (i + 1, ("RTT=%sms" % mm.group(1)) if mm else "TIMEOUT"))
    if rtts:
        print("[RF] ping 成功率 %d/%d  RTT %s" % (len(rtts), args.rounds, rtts))
    else:
        print("[RF] ping 全失败 —— 链路已断，不是 TCP 层问题")

    # ---- 2. TCP 建连反复尝试 ----
    print("\n[TCP] AP 开服务端 %d" % args.port)
    print("   AP CIPMUX=1     ->", one(apm, "AT+CIPMUX=1"))
    print("   AP CIPSERVER=1  ->", one(apm, "AT+CIPSERVER=1,%d" % args.port, 8.0))
    print("   AP CIPSTATE     ->", one(apm, "AT+CIPSTATE")[:60])

    print("\n[TCP] STA 反复建连 x%d" % args.rounds)
    ok = 0
    for i in range(args.rounds):
        one(sta, "AT+CIPMUX=0")
        r = one(sta, 'AT+CIPSTART="TCP","%s",%d' % (ap_ip, args.port), 14.0)
        good = "CONNECT" in r
        ok += 1 if good else 0
        print("   第%d次 %s  %s" % (i + 1, "成功 ✓" if good else "失败 ✗", r[:46]))
        if not good:
            one(sta, "AT+CIPCLOSE", 4.0)
            one(sta, "AT+CIPCLOSE=5", 4.0)
    print("\n[TCP] 建连成功率 %d/%d" % (ok, args.rounds))
    print("[结论] ping 通但 TCP 时通时不通 => RF 抖动（环境）；两者都失败 => 链路或固件问题")

    sta.close()
    apm.close()


if __name__ == "__main__":
    main()