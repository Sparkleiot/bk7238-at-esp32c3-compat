#!/usr/bin/env bash
# gen_patch.sh —— 由 src/vendor-pristine/ 与 src/modified/ 生成统一 diff 补丁
#
# 说明:
#   * 只覆盖「修改」的文件; 新文件 atsvr_esp_compat.c 由 src/apply.sh 直接拷贝,
#     不进补丁 (避免 patch 处理 /dev/null 新建的兼容性问题)。
#   * patch 里的 +++ 路径是相对 SDK 根目录的 (带 a/ b/ 前缀), 因此可在 SDK 根执行:
#         patch -p1 < docs/patches/esp32c3-compat.patch
#
#   * 行尾说明: MSYS2 下的 diff/sed/patch 都按文本模式处理, CR 会被丢弃。
#     SDK 原始文件是 CRLF, 因此本补丁是 LF 归一化形式 —— 这也正是该平台
#     patch 唯一能接受的形式 (CRLF 补丁会报 "different line endings" 而失败)。
#     应用后文件变成 LF, GCC 不区分, 功能完全一致。
#     如果需要与 src/modified/ 字节级一致, 请用 src/apply.sh (直接拷贝)。
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
OUT="$ROOT/docs/patches/esp32c3-compat.patch"

# modified文件 : SDK相对路径
PAIRS="
_atsvr_func.c:beken378/func/at_server/at_server_func/_atsvr_func.c
application.mk:application.mk
at_svr_opts.h:beken378/func/at_server/include/at_svr_opts.h
atsvr_cmd.c:beken378/func/at_server/atsvr_cmd/atsvr_cmd.c
atsvr_mqtt_cmd.c:beken378/func/at_server/mqtt/atsvr_mqtt_cmd.c
atsvr_net_cmd.c:beken378/func/at_server/atsvr_net_cmd/atsvr_net_cmd.c
atsvr_wlan.c:beken378/func/at_server/atsvr_cmd/atsvr_wlan.c
beken_src.mk:beken378/beken_src.mk
network_app.c:beken378/func/at_server/network/network_app.c
ping.c:beken378/func/lwip_intf/lwip-2.0.2/src/apps/ping/ping.c
HAL_TCP_lwip.c:beken378/func/at_server/network/net_hal/HAL_TCP_lwip.c
"

{
  echo "# BK7238 / XH-WB3S  ——  ESP32-C3 (ESP-AT) 兼容改造补丁"
  echo "# 生成时间: $(date '+%Y-%m-%d %H:%M:%S')"
  echo "# 应用方式: cd <SDK根> && patch -p1 < docs/patches/esp32c3-compat.patch"
  echo "# 新增文件 atsvr_esp_compat.c 不在本补丁内, 由 src/apply.sh 直接拷贝。"
  echo
} > "$OUT"

n=0
for pair in $PAIRS; do
  m="${pair%%:*}"
  rel="${pair#*:}"
  a="$ROOT/src/vendor-pristine/$m.orig"
  b="$ROOT/src/modified/$m"
  if [ ! -f "$a" ]; then echo "!! 缺少原始副本: $a" >&2; exit 1; fi
  if [ ! -f "$b" ]; then echo "!! 缺少修改版本: $b" >&2; exit 1; fi
  diff -u "$a" "$b" \
    | sed -e "1s|^--- .*|--- a/$rel|" -e "2s|^+++ .*|+++ b/$rel|" >> "$OUT"
  n=$((n + 1))
done

echo "[patch] 已生成 $OUT  (覆盖 $n 个修改文件, $(wc -l < "$OUT") 行)"
