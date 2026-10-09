"""UDP 透传数据面定向复现：区分「固件缺陷」与「RF 丢包」。

背景：m2m 里 UDP 普通模式(#30/#31) 全 PASS，唯独 UDP 透传(#35/#36) 偶发失败。
本脚本在同一组网链路上交替跑「UDP 普通」与「UDP 透传」各N轮，
若普通稳定而透传稳定失败 => 固件缺陷；两者都偶发 => RF 丢包。

用法: python tools/udp_passthru_probe.py --sta COM5 --ap COM7 --rounds 3
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


def cmd(s, line, wait=6.0):
    """发一条命令/裸数据并等待。line 可以是 str(自动补 CRLF) 或 bytes(原样发)。"""
    s.reset_input_buffer()
    s.write((line + "\r\n").encode() if isinstance(line, str) else line)
    time.sleep(wait)
    return s.read_all()


def text(s, line, wait=6.0):
    return " ".join(cmd(s, line, wait).decode("utf-8", "replace")
                    .replace("\r", "").replace("\n", " ").split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sta", default="COM5")
    ap.add_argument("--ap", default="COM7")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--ssid", default="BK-M2M")
    ap.add_argument("--pwd", default="12345678")
    ap.add_argument("--apip", default="192.168.4.1")
    args = ap.parse_args()

    sta = open_at(args.sta)
    apm = open_at(args.ap)
    text(sta, "AT")
    text(apm, "AT")

    # 数据面自检: STA 显示"已关联"但 ping 不通 AP => 会话已失效 /
    # SoftAP beacon 停了 (见 2026-10-09 日志)。此时跑什么都是假的。
    #
    # 注意: 不能因为"有 IP"就跳过重连 —— AP 模组 AT+RST 后, STA 手里还攥着
    # 上一轮的 IP 与关联状态, 看着像连着, 实际 AP 侧已经没有它了。
    # 所以这里以 ping 通不通为准, 不通就退网等后台自动重连, 再自检一次。
    def data_plane_ok():
        r = text(sta, 'AT+PING="%s"' % args.apip, 12.0)
        return "TIMEOUT" not in r, r

    ok, base = data_plane_ok()
    print("[基线] STA ping AP ->", base[:40])
    if not ok:
        print("[自愈] 数据面不通，轮询等后台自动重连（不再显式 CWJAP）")
        # 显式 AT+CWJAP 在 RF 劣化时段会一直回 OK 却拿不到 IP，
        # 真正能把链路拉起来的是模块后台的自动重连 —— 所以这里只轮询 CIFSR。
        # 参见 at_module_to_module_test.py 里 ensure_ip() 的注释。
        text(sta, "AT+CWQAP", 8.0)
        t0 = time.time()
        got = ""
        while time.time() - t0 < 180:
            time.sleep(5)
            got = text(sta, "AT+CIFSR", 3.0)
            if "0.0.0.0" not in got:
                break
        print("      等IP 用时 %ds -> %s" % (int(time.time() - t0), got[:50]))
        ok, base = data_plane_ok()
        print("[自愈后] STA ping AP ->", base[:40])
    if not ok:
        print("[中止] 等待 180s 后数据面仍不通 —— SoftAP 侧 beacon 未广播。")
        print("      先跑 tools/beacon_check.py --sta %s 确认。" % args.sta)
        sta.close()
        apm.close()
        return

    normal_ok = pass_ok = 0
    for i in range(args.rounds):
        print("\n===== 第 %d 轮 =====" % (i + 1))

        # ---------- A. UDP 普通模式 ----------
        text(sta, "AT+CIPMUX=0")
        text(sta, "AT+CIPMODE=0")
        text(apm, "AT+CIPMUX=1")
        text(apm, 'AT+CIPSERVER=1,,"UDP"', 8.0)
        text(sta, 'AT+CIPSTART="UDP","%s",8899' % args.apip, 12.0)
        cmd(sta, "AT+CIPSEND=12")
        time.sleep(0.5)
        cmd(sta, b"UDP-FROM-STA")
        ap_raw = cmd(apm, "", 6.0).decode("utf-8", "replace")
        ok = "UDP-FROM-STA" in ap_raw
        normal_ok += 1 if ok else 0
        print("  [普通] STA->AP 数据: %s" % ("收到 ✓" if ok else "未收到 ✗"))
        text(sta, "AT+CIPCLOSE", 4.0)
        text(apm, "AT+CIPSERVER=0", 4.0)

        # ---------- B. UDP 透传模式 ----------
        text(sta, "AT+CIPMUX=0")
        text(sta, "AT+CIPMODE=1")
        text(apm, "AT+CIPMUX=1")
        text(apm, 'AT+CIPSERVER=1,,"UDP"', 8.0)
        r = text(sta, 'AT+CIPSTART="UDP","%s",8899' % args.apip, 14.0)
        print("  [透传] CIPSTART: %s" % ("CONNECT ✓" if "CONNECT" in r else r[:40]))
        cmd(sta, "AT+CIPSEND")
        time.sleep(0.5)
        # 裸数据（透传模式无回显/无 +IPD）
        sta.reset_input_buffer()
        sta.write(b"UDP-PASSTHRU-DATA")
        time.sleep(1.0)
        sta.write(b"\x1a\x1a\x1a")  # 结束标记
        ap_raw = cmd(apm, "", 8.0).decode("utf-8", "replace")
        ok = "UDP-PASSTHRU-DATA" in ap_raw
        pass_ok += 1 if ok else 0
        print("  [透传] STA->AP 数据: %s" % ("收到 ✓" if ok else "未收到 ✗"))
        # 退出透传
        sta.reset_input_buffer()
        sta.write(b"+++")
        time.sleep(1.5)
        sta.read_all()
        time.sleep(1.0)
        print("  [透传] +++ 后 AT: %s"
              % ("恢复 ✓" if "OK" in text(sta, "AT") else "未恢复 ✗"))
        text(sta, "AT+CIPMODE=0", 3.0)

    print("\n===== 汇总 =====")
    print("  UDP 普通  %d/%d" % (normal_ok, args.rounds))
    print("  UDP 透传  %d/%d" % (pass_ok, args.rounds))
    print("  判据: 普通稳/透传稳失败 => 固件缺陷；两者都偶发 => RF 丢包")

    sta.close()
    apm.close()


if __name__ == "__main__":
    main()