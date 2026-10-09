#!/usr/bin/env python3
"""把 AP 模组拉起来并保持广播，进程退出后 AP 继续工作。

因为 AP 配置会写进模组，不需要一直占着串口 —— 起一次就能给
tools/sta_trace.py 之类的 STA 侧脚本反复用。

用法:
    python tools/m2m_ap_up.py [ecn] [ssid] [pwd] [port]
        ecn  0=open 2=WPA_AES 3=WPA2_AES 4=WPA2_MIXED  (默认 3)
        port 默认 COM6
"""
import sys
import time

from ap_wpa_trace import Port


def main():
    ecn = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    ssid = sys.argv[2] if len(sys.argv) > 2 else "BK-M2M"
    pwd = sys.argv[3] if len(sys.argv) > 3 else "12345678"
    port = sys.argv[4] if len(sys.argv) > 4 else "COM6"

    p = Port("AP", port)
    try:
        print(f"[ap-up] {port}  ssid={ssid}  pwd={pwd!r}  ecn={ecn}")
        p.send("AT+RST")
        time.sleep(14)
        p.clear()
        p.send("AT+CWMODE=2")
        time.sleep(2)
        p.send(f'AT+CWSAP="{ssid}","{pwd}",1,{ecn}')
        time.sleep(8)
        p.send("AT+CWSAP?")
        time.sleep(2)
        p.send("AT+CIPAP?")
        time.sleep(2)
        # CWSAP?/CIPAP? 在 AP 日志刷屏下可能被截断，只做参考
        txt = p.text().replace("\r", "")
        for ln in txt.split("\n"):
            if "CWSAP:" in ln or "CIPAP:" in ln or ln.strip() == "OK":
                print("   ", ln.strip())
        print("[ap-up] AP 已启动，可以断开串口（AP 会继续广播）")
    finally:
        p.close()


if __name__ == "__main__":
    main()
