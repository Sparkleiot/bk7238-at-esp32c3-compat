#!/usr/bin/env bash
# apply.sh —— 把 src/modified/ 下的 ESP-AT 兼容改动应用到 SDK 源码树
#
# 用法: bash src/apply.sh [SDK根目录]
#   默认 SDK 根目录: ./sdk/BK7238-AT
#
# 改动清单:
#   A. AT 命令层/协议栈(16 个已改文件, 原始副本见 src/vendor-pristine/)
#      - 新增 atsvr_esp_compat.c          兼容层(新命令 + 动态应答前缀)
#                                         + 自研 ICMP Echo(AT+PING 用;
#                                         不动 lwIP 的 GPL 版 ping.c)
#      - 改   atsvr_cmd.c                 命令改名/别名 + 应答名跟随实际命令
#      - 改   atsvr_wlan.c                CWLAP 的 BSSID 去掉尾空格
#      - 改   atsvr_wlan.h                atsvr_ecn_to_bk_sec() 声明
#      - 改   wlan_ui.c                   SoftAP 走 network_InitTypeDef_ap_st
#                                         (带 security), 修 bk_wlan_ap_init_adv
#                                         的 ssid/key 收尾 + 补 wlan_ap_set()
#      - 改   hostapd_intf.c              hapd_intf_del_key 拒绝
#                                         rwm_mgmt_get_hwkeyidx() 的哨兵值
#                                         (MM_SEC_MAX_KEY_NBR+1 = 65, 会误删
#                                          MFP key, 导致 WPA2 关联即断)
#      - 改   atsvr_net_cmd.c             CIPDOMAIN 引号 / 失败时回 ERROR
#                                         CIPSTART 支持域名 / PING 改 ESP-AT 格式
#      - 改   network_app.c               +BIPSTATUS -> STATUS:/+CIPSTATUS:
#      - 改   atsvr_mqtt_cmd.c            +MQTTCONNSTATE -> +MQTTCONN
#                                         MQTTUSERCFG scheme 按 ESP-AT 语义映射
#                                         (1=TCP / 2..4=TLS, 原厂 1 误当 TLS)
#      - 改   qcloud_at_mqtt.c            订阅收包上报改 ESP-AT 事件
#                                         +MQTTSUBRECV:<id>,"topic",<len>,<data>
#                                         (原厂 "+MQTTSUBREV:..." 拼错且无 link id)
#      - 改   atsvr_http_cmd.c            HTTPCLIENT/HTTPGETSIZE 输出格式对齐
#                                         ESP-AT(去掉写死的占位尖括号) + HTTPS
#                                         正文偏移按 "\r\n\r\n"+4 定位
#      - 改   utils_httpc.c               user_httpclient_recv_response:
#                                         size 只上报一次(修 HTTPGETSIZE 无限
#                                         重复) + 分片响应首包正文不再丢
#      - 改   atsvr_port.c               上电恢复 SoftAP: 等 5s 栈热身后
#                                         走 stop->start 干净路径; 且改由独立
#                                         线程异步执行(同步阻塞会让复位后
#                                         5.5s 内 AT 完全不响应, 并制造
#                                         "系统全空闲"窗口 -> MCU 省电路径
#                                         卡死 tick -> 看门狗 boot-loop)
#      - 改   _atsvr_func.c               AT+GMR 改为 ESP-AT 四行格式
#      - 改   at_svr_opts.h               去掉 CMDRSP: 前缀 / 事件文案
#      - 改   beken_src.mk                把兼容层加入编译
#      - 改   HAL_TCP_lwip.c              connect 改非阻塞+select 10s 超时
#      - 改   HAL_TLS_mbedtls.c           AT+CIPSTART="TLS" 能力缺口:
#                                         authmode 不再硬编码 VERIFY_REQUIRED
#                                         (改为按 AT+CIPSSLCCONF 的 auth_mode,
#                                          0=不认证, 与 ESP-AT 一致);
#                                         conf_own_cert 只在有客户端证书时才调;
#                                         PSK 长度校验(越界会 0x7100 直接打死连接);
#                                         read_timeout=0 兜底;
#                                         读返回值 0 不再当致命错误(会误杀空闲链路);
#                                         读到的数据不再要求填满缓冲才交付
#                                         (与 TCP 的单次 recv 语义对齐, 否则小包被丢弃)
#      - 改   HAL_DTLS_mbedtls.c          同上的 auth_mode 与 read 返回值问题
#      - 改   application.mk              include 列表落成 GCC 响应文件,
#                                         规避宿主 shell 约 8KB 的命令行上限
#   B. 构建脚本层(见 tools/patch_build_scripts.py, 备份后缀 .orig2)
#      - tools/scripts/generate_sys_config.sh   去掉会被安全垫片拦截的冗余 rm
#      - tools/scripts/pick_beken_libs.sh       同上
#      - tools/beken_packager/beken_packager_wrapper
#                                               move->copy, 不再删 tmp.json
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
SDK="${1:-$ROOT/sdk/BK7238-AT}"
BK="$SDK/beken378"

if [ ! -d "$BK" ]; then
  echo "!! 找不到 SDK 源码树: $BK" >&2
  exit 1
fi

cp "$HERE/modified/at_svr_opts.h"       "$BK/func/at_server/include/at_svr_opts.h"
cp "$HERE/modified/atsvr_cmd.c"         "$BK/func/at_server/atsvr_cmd/atsvr_cmd.c"
cp "$HERE/modified/atsvr_esp_compat.c"  "$BK/func/at_server/atsvr_cmd/atsvr_esp_compat.c"
cp "$HERE/modified/atsvr_wlan.c"        "$BK/func/at_server/atsvr_cmd/atsvr_wlan.c"
cp "$HERE/modified/atsvr_wlan.h"        "$BK/func/at_server/atsvr_cmd/atsvr_wlan.h"
cp "$HERE/modified/atsvr_port.c"        "$BK/func/at_server/_at_server_port/atsvr_port.c"
cp "$HERE/modified/atsvr_net_cmd.c"     "$BK/func/at_server/atsvr_net_cmd/atsvr_net_cmd.c"
cp "$HERE/modified/network_app.c"       "$BK/func/at_server/network/network_app.c"
cp "$HERE/modified/atsvr_mqtt_cmd.c"    "$BK/func/at_server/mqtt/atsvr_mqtt_cmd.c"
cp "$HERE/modified/qcloud_at_mqtt.c"    "$BK/func/at_server/mqtt/qcloud_at_mqtt.c"
cp "$HERE/modified/atsvr_http_cmd.c"    "$BK/func/at_server/atsvr_http_cmd/atsvr_http_cmd.c"
cp "$HERE/modified/utils_httpc.c"       "$BK/app/http/utils_httpc.c"
cp "$HERE/modified/_atsvr_func.c"       "$BK/func/at_server/at_server_func/_atsvr_func.c"
cp "$HERE/modified/wlan_ui.c"           "$BK/func/wlan_ui/wlan_ui.c"
cp "$HERE/modified/net.c"               "$BK/func/lwip_intf/lwip-2.0.2/port/net.c"
cp "$HERE/modified/dhcp-server.c"      "$BK/func/lwip_intf/dhcpd/dhcp-server.c"
cp "$HERE/modified/dhcp-server-main.c"  "$BK/func/lwip_intf/dhcpd/dhcp-server-main.c"
cp "$HERE/modified/dhcp-priv.h"         "$BK/func/lwip_intf/dhcpd/dhcp-priv.h"
cp "$HERE/modified/hostapd_intf.c"      "$BK/func/hostapd_intf/hostapd_intf.c"
cp "$HERE/modified/beken_src.mk"        "$BK/beken_src.mk"
cp "$HERE/modified/HAL_TCP_lwip.c"     "$BK/func/at_server/network/net_hal/HAL_TCP_lwip.c"
cp "$HERE/modified/HAL_UDP_lwip.c"     "$BK/func/at_server/network/net_hal/HAL_UDP_lwip.c"
cp "$HERE/modified/HAL_TLS_mbedtls.c"  "$BK/func/at_server/network/net_hal/HAL_TLS_mbedtls.c"
cp "$HERE/modified/HAL_DTLS_mbedtls.c" "$BK/func/at_server/network/net_hal/HAL_DTLS_mbedtls.c"
cp "$HERE/modified/network_socket.c"    "$BK/func/at_server/network/network_socket.c"
cp "$HERE/modified/network_interface.h" "$BK/func/at_server/network/network_interface.h"
cp "$HERE/modified/application.mk"      "$SDK/application.mk"
cp "$HERE/modified/sys_config_bk7238.h" "$BK/app/config/sys_config_bk7238.h"

echo "[apply] 已应用 28 个文件到 $BK"
echo "[apply] (27 个修改 + 1 个新增 atsvr_esp_compat.c)"
echo "[apply] 注: sys_config_bk7238.h 目前与厂商原版一致(纳入跟踪是为了防止"
echo "[apply]     再次被改坏 —— 2026-10-07 曾把 CFG_USE_MCU_PS/CFG_USE_STA_PS"
echo "[apply]     改成 0, 导致上电 SoftAP 恢复路径卡死 + 看门狗 boot-loop)。"
echo "[apply] 注: lwIP 自带的 ping.c(GPL v2/v3)**不做任何改动**, AT+PING 的"
echo "[apply]     ICMP 实现已改为在 atsvr_esp_compat.c 里自研, SDK 侧保持原样。"

# 构建脚本层补丁(可重复执行, 幂等)
if [ "${SKIP_BUILD_PATCH:-0}" != "1" ]; then
  PY=""
  for p in "$ROOT/tools/py/python.exe" \
           "C:/Users/99471/.workbuddy/binaries/python/versions/3.13.12/python.exe"; do
    [ -x "$p" ] && { PY="$p"; break; }
  done
  if [ -n "$PY" ] && [ -f "$ROOT/tools/patch_build_scripts.py" ]; then
    "$PY" "$ROOT/tools/patch_build_scripts.py" || true
  fi
fi
