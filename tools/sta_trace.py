#!/usr/bin/env python3
"""单个模组做 STA 的关联追踪（用于对比「连我们自己的 SoftAP」与「连真实 AP」）。

用法:
    python tools/sta_trace.py COM5 MyHomeWiFi <pwd> [--nolog]

默认先发 ATE1 打开 log_output_state(1)，这样 wpa_supplicant 的
bk_printf 日志会出现在 AT 串口上。--nolog 则不发 ATE1（日志关闭），
用于排除「日志本身是否影响握手」。
"""
import sys
import time

from ap_wpa_trace import Port


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
    ssid = sys.argv[2] if len(sys.argv) > 2 else "MyHomeWiFi"
    pwd = sys.argv[3] if len(sys.argv) > 3 else ""
    nolog = "--nolog" in sys.argv

    p = Port("STA", port)
    try:
        print(f"[sta] {port} -> SSID={ssid} pwd={pwd!r} nolog={nolog}")
        p.send("AT+RST")
        time.sleep(14)
        p.clear()
        if not nolog:
            p.send("ATE1")
            time.sleep(1.5)
        p.send(f'AT+CWJAP="{ssid}","{pwd}"')
        t_end = time.time() + 40
        got = False
        while time.time() < t_end:
            time.sleep(0.5)
            if "WIFI GOT IP" in p.text():
                got = True
                break
        log = p.text()
        print(f"[sta] WIFI GOT IP: {got}")
        print("---------- RAW ----------")
        print(log.replace("\r", "")[-9000:])
        print("-------------------------")
        p.send("AT+CIFSR")
        time.sleep(2)
        print("[sta] CIFSR:", p.text()[-500:].replace("\r", ""))
        with open("test/sta_trace.md", "w", encoding="utf-8") as f:
            f.write(f"# STA trace {ssid} port={port} nolog={nolog}\n\n```\n")
            f.write(log.replace("\r", ""))
            f.write("\n```\n")
    finally:
        p.close()


if __name__ == "__main__":
    main()
