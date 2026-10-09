#!/usr/bin/env python3
"""BK7238 双模组 SoftAP WPA2 关联 —— 带 AP 侧原始日志的追踪。

诊断版固件在 bk_wlan_start_ap_adv() 里调用 log_output_state(1)，
因此 hostapd / wpa_supplicant 的 bk_printf 日志会落到 UART1，
也就是 AT 串口。本脚本用两个线程同时抓 AP 与 STA 的原始回包，
不做任何 reset_input_buffer，以便看到 AP 侧握手全过程。

用法:
    python tools/ap_wpa_trace.py [ecn] [ssid] [pwd]
        ecn 默认 3 (WPA2_PSK)

注意(踩过的坑)
--------------
AT 应答和 wpa/hostapd 日志共用同一个 UART，两条线程会按字节交错，
所以 "WIFI GOT IP" 可能被写成 "WIFI Gtemp_codOT Ie:..."，
"AT+CWLAP=\"BK-M2M\"" 的命令回显里也含 ssid —— 直接 in 判断会假阳性。
因此本脚本:
  * 复位后先给 STA 发 ATE0 静音，保证 AT 应答不被日志打断；
  * 扫描结果只认 "+CWLAP:" 正则，不认回声里的 ssid；
  * 最终判定改用 AT 查询 (AT+CWJAP? / AT+CIPSTA?)，不认被打断的文本。
"""
import re
import sys
import threading
import time

import serial

AP_PORT = "COM6"
STA_PORT = "COM5"
BAUD = 115200


class Port:
    def __init__(self, name, port):
        self.name = name
        self.ser = serial.Serial(port, BAUD, timeout=0.05)
        self.buf = []
        self.stop = False
        self.lock = threading.Lock()
        self.t0 = time.time()
        self.th = threading.Thread(target=self._reader, daemon=True)
        self.th.start()

    def _reader(self):
        while not self.stop:
            try:
                n = self.ser.in_waiting
                data = self.ser.read(n if n else 1)
            except Exception:  # noqa: BLE001
                break
            if data:
                ts = time.time() - self.t0
                with self.lock:
                    self.buf.append((ts, data.decode("utf-8", "replace")))

    def text(self):
        with self.lock:
            return "".join(txt for _, txt in self.buf)

    def clear(self):
        with self.lock:
            self.buf.clear()

    def since(self, ts):
        with self.lock:
            return "".join(txt for t, txt in self.buf if t >= ts)

    def lines(self, ts):
        """返回 [(相对秒, 文本行)]，用于两个端口按时间合并。"""
        out = []
        with self.lock:
            for t, txt in self.buf:
                if t < ts:
                    continue
                for ln in txt.replace("\r", "").split("\n"):
                    if ln.strip():
                        out.append((t, ln))
        return out

    def send(self, line):
        self.ser.write((line + "\r\n").encode())
        self.ser.flush()

    def close(self):
        self.stop = True
        time.sleep(0.1)
        try:
            self.ser.close()
        except Exception:  # noqa: BLE001
            pass


def show(title, text, maxlen=6000):
    print(f"\n---------- {title} ({len(text)} 字符) ----------")
    if len(text) > maxlen:
        print(f"...[前 {len(text)-maxlen} 字符省略]...")
        text = text[-maxlen:]
    print(text.replace("\r", ""))


def main():
    ecn = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    ssid = sys.argv[2] if len(sys.argv) > 2 else "BK-M2M"
    pwd = sys.argv[3] if len(sys.argv) > 3 else "12345678"

    print(f"[trace] AP={AP_PORT}  STA={STA_PORT}  ecn={ecn}  ssid={ssid}  pwd={pwd!r}")
    ap = Port("AP", AP_PORT)
    sta = Port("STA", STA_PORT)
    lines = []
    try:
        print("[1] AT+RST 复位两块模组 ...")
        ap.send("AT+RST")
        sta.send("AT+RST")
        time.sleep(14)
        # STA 先静音：否则 wpa 日志会把 AT 应答按字节打断，判定全部失真
        sta.send("ATE0")
        time.sleep(0.6)
        ap.clear()
        sta.clear()

        mark_ap = time.time() - ap.t0
        print("[2] AP: CWMODE=2 -> CWSAP")
        ap.send("AT+CWMODE=2")
        time.sleep(1.5)
        ap.send(f'AT+CWSAP="{ssid}","{pwd}",1,{ecn}')
        time.sleep(6)

        print("[3] STA: 扫描")
        sta.send(f'AT+CWLAP="{ssid}"')
        time.sleep(12)
        scan = sta.since(mark_ap)
        # 只认真正的扫描结果行：命令回显里也含 ssid，用 in 判断会假阳性
        found = bool(re.search(r"\+CWLAP:\(", scan))

        print("[4] STA: CWJAP")
        sta.send(f'AT+CWJAP="{ssid}","{pwd}"')
        time.sleep(28)

        print("[5] STA: AT+CWJAP? / AT+CIPSTA? 复核（权威判定）")
        sta.clear()
        sta.send("AT+CWJAP?")
        time.sleep(2)
        q1 = sta.text()
        sta.clear()
        sta.send("AT+CIPSTA?")
        time.sleep(2)
        q2 = sta.text()
        m_ip = re.search(r'\+CIPSTA:ip:"([^"]+)"', q2)
        ip = m_ip.group(1) if m_ip else "(无)"
        cwjap = ("No AP" if "No AP" in q1
                 else "+CWJAP: (已连接)" if "+CWJAP:" in q1
                 else "(超时/未应答)")
        got_ip = ip not in ("(无)", "0.0.0.0")
        print(f"    扫描={found}  CWJAP?={cwjap}  STA IP={ip}  ==> {'PASS' if got_ip else 'FAIL'}")

        ap_log = ap.since(mark_ap)
        sta_log = sta.since(mark_ap)

        # 合并时间线（关键！能看出是哪一侧先拆链）
        merged = sorted(
            [(t, "AP ", ln) for t, ln in ap.lines(mark_ap)]
            + [(t, "STA", ln) for t, ln in sta.lines(mark_ap)]
        )
        print("\n---------- 合并时间线 ----------")
        for t, who, ln in merged:
            print(f"{t:7.3f} {who} | {ln}")

        show("AP 原始输出 (含 hostapd 日志)", ap_log, 12000)
        show("STA 原始输出", sta_log, 4000)

        lines.append(f"ecn={ecn} ssid={ssid} pwd={pwd} 扫描={'FOUND' if found else 'NOT FOUND'}")
        lines.append(f"STA 关联判定: {cwjap}")
        lines.append(f"STA 是否拿到 IP: {got_ip}  (AT+CIPSTA? = {ip})")
        lines.append("")
        lines.append("===== 合并时间线 =====")
        lines.append("```")
        for t, who, ln in merged:
            lines.append(f"{t:7.3f} {who} | {ln}")
        lines.append("```")
        lines.append("")
        lines.append("===== AP RAW =====")
        lines.append(ap_log.replace("\r", ""))
        lines.append("")
        lines.append("===== STA RAW =====")
        lines.append(sta_log.replace("\r", ""))


        out = "test/ap_wpa_trace.md"
        with open(out, "w", encoding="utf-8") as f:
            f.write("# BK7238 SoftAP WPA2 关联追踪\n\n```\n")
            f.write("\n".join(lines))
            f.write("\n```\n")
        print(f"\n[trace] 已写入 {out}")
    finally:
        ap.close()
        sta.close()


if __name__ == "__main__":
    main()
