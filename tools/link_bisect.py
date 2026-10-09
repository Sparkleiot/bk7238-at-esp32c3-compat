"""双向定位：STA 关联后 ping 不通 AP，到底是哪一侧坏了。

用法: python tools/link_bisect.py --sta COM5 --ap COM7
输出: STA 侧视角(能否 ping AP) + AP 侧视角(能否 ping STA) + 双方 IP/关联状态。
判读:
  - 两侧都ping 不通  => 数据面(netif/DHCP)问题
  - 只有一侧不通    => 该侧 ICMP/回程路由问题
  - 两侧都通         => 链路正常(之前的失败是时序)
"""
import argparse
import time

import serial


def open_at(port):
    s = serial.Serial(port, 115200, timeout=1.0)
    s.reset_input_buffer()
    s.write(b"ATE0\r\n")
    time.sleep(2.0)
    s.read_all()
    return s


def text(s, line, wait=6.0):
    s.reset_input_buffer()
    s.write((line + "\r\n").encode())
    time.sleep(wait)
    return " ".join(s.read_all().decode("utf-8", "replace")
                    .replace("\r", "").replace("\n", " ").split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sta", default="COM5")
    ap.add_argument("--ap", default="COM7")
    ap.add_argument("--apip", default="192.168.4.1")
    ap.add_argument("--ssid", default="BK-M2M")
    ap.add_argument("--pwd", default="12345678")
    args = ap.parse_args()

    sta = open_at(args.sta)
    apm = open_at(args.ap)
    text(sta, "AT")
    text(apm, "AT")

    print("=== 1. AP 侧状态 ===")
    print("  CWMODE? ->", text(apm, "AT+CWMODE?", 3.0)[:35])
    print("  CWSAP?  ->", text(apm, "AT+CWSAP?", 3.0)[:50])
    print("  CIPAP?  ->", text(apm, "AT+CIPAP?", 4.0)[:70])

    print("\n=== 2. STA 重新关联 ===")
    text(sta, 'AT+CWJAP="%s","%s",1' % (args.ssid, args.pwd), 25.0)
    j = text(sta, "AT+CWJAP?", 6.0)
    print("  CWJAP?  ->", j[:75])
    ip = text(sta, "AT+CIFSR", 4.0)
    print("  CIFSR   ->", ip[:70])
    sta_ip = ""
    for tok in ip.split():
        if tok.count(".") == 3 and not tok.endswith('"'):
            sta_ip = tok.strip('"')
            break
    print("  STA IP  =", sta_ip or "(未获取)")

    print("\n=== 3. STA -> AP 方向 ===")
    r = text(sta, 'AT+PING="%s"' % args.apip, 14.0)
    print("  STA ping %s -> %s" % (args.apip, r[:45]))

    print("\n=== 4. AP -> STA 方向 ===")
    if sta_ip:
        r2 = text(apm, 'AT+PING="%s"' % sta_ip, 14.0)
        print("  AP ping %s -> %s" % (sta_ip, r2[:45]))
    else:
        print("  STA 无 IP，跳过")

    print("\n=== 5. TCP 端口连通（绕开 ICMP）===")
    text(apm, "AT+CIPMUX=1")
    print("  AP CIPSERVER ->", text(apm, "AT+CIPSERVER=1,8899", 8.0)[:35])
    text(sta, "AT+CIPMUX=0")
    r3 = text(sta, 'AT+CIPSTART="TCP","%s",8899' % args.apip, 15.0)
    print("  STA CIPSTART->", ("CONNECT ✓" if "CONNECT" in r3 else r3[:45]))

    print("\n=== 判读 ===")
    sta_ok = "TIMEOUT" not in r
    ap_ok = ("TIMEOUT" not in r2) if sta_ip else False
    tcp_ok = "CONNECT" in r3
    print("  STA->AP ICMP :", "通" if sta_ok else "不通")
    print("  AP->STA ICMP :", "通" if ap_ok else "不通")
    print("  STA->AP TCP  :", "通" if tcp_ok else "不通")
    if not sta_ok and not tcp_ok:
        print("  => 数据面不通：SoftAP 侧 netif/DHCP 或 beacon 状态异常")
    elif not sta_ok and tcp_ok:
        print("  => 仅 ICMP 不通，TCP 正常 => ICMP 回程/自身实现问题，不影响业务")
    else:
        print("  => 链路正常")

    sta.close()
    apm.close()


if __name__ == "__main__":
    main()