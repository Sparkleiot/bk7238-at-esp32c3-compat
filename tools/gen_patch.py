#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""重新生成 docs/patches/esp32c3-compat.patch。

补丁 = src/vendor-pristine/<file>.orig  ->  src/modified/<file>
路径按 SDK 根目录写成 a/beken378/... / b/beken378/...（便于 patch -p1）。

新增文件 atsvr_esp_compat.c 不在补丁里（由 src/apply.sh 直接拷贝），
构建脚本层的三处改动由 tools/patch_build_scripts.py 负责。

用法: python tools/gen_patch.py
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRISTINE = os.path.join(ROOT, "src", "vendor-pristine")
MODIFIED = os.path.join(ROOT, "src", "modified")
OUT = os.path.join(ROOT, "docs", "patches", "esp32c3-compat.patch")

# modified 文件名 -> SDK 根目录下的相对路径
FILES = {
    "_atsvr_func.c":     "beken378/func/at_server/at_server_func/_atsvr_func.c",
    "at_svr_opts.h":     "beken378/func/at_server/include/at_svr_opts.h",
    "atsvr_cmd.c":       "beken378/func/at_server/atsvr_cmd/atsvr_cmd.c",
    "atsvr_mqtt_cmd.c":  "beken378/func/at_server/mqtt/atsvr_mqtt_cmd.c",
    "qcloud_at_mqtt.c":  "beken378/func/at_server/mqtt/qcloud_at_mqtt.c",
    "atsvr_http_cmd.c":  "beken378/func/at_server/atsvr_http_cmd/atsvr_http_cmd.c",
    "utils_httpc.c":     "beken378/app/http/utils_httpc.c",
    "atsvr_net_cmd.c":   "beken378/func/at_server/atsvr_net_cmd/atsvr_net_cmd.c",
    "atsvr_wlan.c":      "beken378/func/at_server/atsvr_cmd/atsvr_wlan.c",
    "atsvr_wlan.h":      "beken378/func/at_server/atsvr_cmd/atsvr_wlan.h",
    "atsvr_port.c":      "beken378/func/at_server/_at_server_port/atsvr_port.c",
    "network_app.c":     "beken378/func/at_server/network/network_app.c",
    "HAL_TCP_lwip.c":    "beken378/func/at_server/network/net_hal/HAL_TCP_lwip.c",
    "HAL_UDP_lwip.c":    "beken378/func/at_server/network/net_hal/HAL_UDP_lwip.c",
    "HAL_TLS_mbedtls.c": "beken378/func/at_server/network/net_hal/HAL_TLS_mbedtls.c",
    "HAL_DTLS_mbedtls.c":"beken378/func/at_server/network/net_hal/HAL_DTLS_mbedtls.c",
    "network_socket.c":  "beken378/func/at_server/network/network_socket.c",
    "network_interface.h":"beken378/func/at_server/network/network_interface.h",
    "hostapd_intf.c":    "beken378/func/hostapd_intf/hostapd_intf.c",
    "wlan_ui.c":         "beken378/func/wlan_ui/wlan_ui.c",
    "net.c":             "beken378/func/lwip_intf/lwip-2.0.2/port/net.c",
    "dhcp-server.c":     "beken378/func/lwip_intf/dhcpd/dhcp-server.c",
    "dhcp-server-main.c":"beken378/func/lwip_intf/dhcpd/dhcp-server-main.c",
    "dhcp-priv.h":       "beken378/func/lwip_intf/dhcpd/dhcp-priv.h",
    "beken_src.mk":      "beken378/beken_src.mk",
    "application.mk":    "application.mk",
    "sys_config_bk7238.h":"beken378/app/config/sys_config_bk7238.h",
}

HEADER = """# BK7238 / XH-WB3S  ——  ESP32-C3 (ESP-AT) 兼容改造补丁
# 生成时间: {ts}
# 应用方式: cd <SDK根> && patch --binary -p1 < docs/patches/esp32c3-compat.patch
#   【必须加 --binary】SDK 源码是 CRLF 行尾, MSYS/Git-Bash 自带的 patch 默认
#   会做 CRLF<->LF 转换, 于是上下文行永远匹配不上, 报
#   "Hunk #N FAILED ... (different line endings)"。--binary 关掉该转换即可。
#
# 本补丁覆盖 {n} 个已改文件。另外两类改动不在本补丁内:
#   1) 新增文件 atsvr_esp_compat.c          -> 由 src/apply.sh 直接拷贝
#   2) 构建脚本层 3 个文件(.orig2 后缀)     -> 由 tools/patch_build_scripts.py 处理
"""


def main():
    missing = []
    chunks = []
    for name in sorted(FILES):
        rel = FILES[name]
        old = os.path.join(PRISTINE, name + ".orig")
        new = os.path.join(MODIFIED, name)
        if not os.path.exists(old):
            missing.append(f"{name}.orig")
            continue
        if not os.path.exists(new):
            missing.append(name)
            continue
        p = subprocess.run(
            ["diff", "-u", f"--label=a/{rel}", f"--label=b/{rel}", old, new],
            capture_output=True,
        )
        if p.returncode == 0:
            print(f"  [跳过] {name} 与 pristine 相同")
            continue
        if p.returncode != 1:
            print(f"  [错误] diff {name}: {p.stderr.decode('utf-8', 'replace')}")
            continue
        chunks.append((name, rel, p.stdout.decode("utf-8", "replace")))

    if missing:
        print("!! 缺少文件: " + ", ".join(missing), file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # 行尾说明: 这里必须用 newline="\n"。
    # SDK 源文件是 CRLF, diff 输出的 hunk 体也自带 CRLF; 若把头部也写成 CRLF,
    # 整份补丁就全是 CRLF, 而 `verify_patch.py` 搭出来的原始树是 LF,
    # `patch --binary` 反而会因 "different line endings" 全部 FAILED。
    # 保持头部 LF / hunk 体 CRLF 的混合形态, 与 verify_patch.py 的期望一致。
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(HEADER.format(ts=time.strftime("%Y-%m-%d %H:%M:%S"), n=len(chunks)))
        for name, rel, body in chunks:
            f.write("\n")
            f.write(body)
            print(f"  [写入] {name:20s} -> {rel}")

    size = os.path.getsize(OUT)
    print(f"\n[gen_patch] {OUT}  ({len(chunks)} 个文件, {size} 字节)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
