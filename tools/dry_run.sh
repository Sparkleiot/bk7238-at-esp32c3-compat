#!/usr/bin/env bash
# dry_run.sh —— 以 -n 方式打印某个目标对象的真实编译命令, 便于定位编译期问题
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
SDK="$ROOT/sdk/BK7238-AT"

TCBIN=""
for d in "$ROOT"/sdk/toolchain/*/bin; do
  [ -x "$d/arm-none-eabi-gcc.exe" ] && { TCBIN="$d"; break; }
done
WIN() { local p="$1"; p="${p#/c/}"; p="${p#/C/}"; echo "C:/$p"; }
export FREERTOS_EXEC_PATH="$(WIN "$TCBIN")/"
export ARM_GCC_TOOLCHAIN="$(WIN "$TCBIN")/"

cd "$SDK" || exit 1
TARGET="${1:-out/./beken378/func/lwip_intf/lwip-2.0.2/src/apps/ping/ping.o}"

"$ROOT/tools/gmake/make.exe" -n -f application.mk \
  "ROOT_DIR=$(WIN "$SDK")" \
  "ENCRYPT=./tools/crc_binary/encrypt.exe" "ENCRYPT_ARGS=" \
  "$TARGET" 2>&1 | tail -12
