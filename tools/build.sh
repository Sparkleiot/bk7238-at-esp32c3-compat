#!/usr/bin/env bash
# build.sh —— 编译 BK7238 AT 固件（ESP32-C3 兼容版）
#
# 环境说明（踩过的坑）:
#   1) 本机没有 make，SDK 自带的 tools/make/make.exe 缺 MinGW 运行库
#      (libintl-8.dll / libgcc_s_dw2-1.dll)，启动即 STATUS_DLL_NOT_FOUND(0xC0000135)。
#      -> 改用 tools/gmake/make.exe（GNU Make 4.4.1, x86_64-w64-mingw32）。
#   2) Makefile 用 `uname` 判平台: Git-Bash 返回 MINGW64_NT-*，既不匹配 MINGW32_NT
#      也不匹配 CYGWIN，于是走 Linux 分支(.sh 脚本)。这正是我们要的——Git-Bash
#      自带 sed/awk/sort/uniq/md5sum/rm，POSIX 脚本可直接跑。
#   3) 但该分支的 ROOT_DIR=$(shell pwd) 会得到 /c/... 形式，原生 arm-none-eabi-gcc.exe
#      不认，所以这里用命令行覆盖为 Windows 风格路径。
#
# 用法: bash tools/build.sh            # 编译 bk7238
#       bash tools/build.sh clean      # 清理
#       bash tools/build.sh -v         # 只编到出 .o 为止的详细输出
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
SDK="$ROOT/sdk/BK7238-AT"

# ---- 1) ARM 工具链 ----
TCBIN=""
for d in "$ROOT"/sdk/toolchain/*/bin "$ROOT"/sdk/toolchain*/bin; do
  if [ -x "$d/arm-none-eabi-gcc.exe" ]; then TCBIN="$d"; break; fi
done
[ -n "$TCBIN" ] || { echo "!! 未找到 arm-none-eabi-gcc.exe，请先解压工具链到 sdk/toolchain/" >&2; exit 1; }

WIN() { local p="$1"; p="${p#/c/}"; p="${p#/C/}"; echo "C:/$p"; }
TCWIN=$(WIN "$TCBIN")
SDKWIN=$(WIN "$SDK")

echo "[toolchain] $TCWIN"
"$TCBIN/arm-none-eabi-gcc.exe" --version | head -1

# application.mk: ARM_GCC_TOOLCHAIN = ${FREERTOS_EXEC_PATH}，结尾必须带 /
export FREERTOS_EXEC_PATH="$TCWIN/"
export ARM_GCC_TOOLCHAIN="$TCWIN/"

# ---- 2) make ----
MAKE="$ROOT/tools/gmake/make.exe"
[ -x "$MAKE" ] || MAKE="$SDK/tools/make/make.exe"
[ -x "$MAKE" ] || { echo "!! 找不到可用的 make" >&2; exit 1; }
echo "[make] $MAKE  ($("$MAKE" --version | head -1))"

# ---- 3) 构建 ----
cd "$SDK" || exit 1
TARGET="${1:-bk7238}"
echo "[build] $TARGET   cwd=$SDK"

# 【重要】命令行长度的坑已经在 application.mk 里从根上解决:
#   INCLUDES 展开后有 11~18KB, 超过本机 shell(PortableGit sh)约 8KB 的
#   命令行上限, 会被从中间截断, gcc 报出误导性的
#       "error: -E or -x required when input is from standard input"
#   或 "fatal error: no input files"。
#   --> application.mk 现在把 include 列表写成 GCC 响应文件(@out/esp_at_includes.rsp),
#       recipe 只剩几十字符, 与 shell 无关。
#   注意: 不要试图把 SHELL 换成 tools/gmake/sh.exe —— 那样虽然命令行够长,
#         但顶层 Makefile 里的 tools/scripts/*.sh 是 #!/bin/bash, busybox 系
#         shell 无法 exec 它们, 构建会停在 "Makefile:147: Error 1"。

# application.mk 用 $(OS) 是否含 "MINGW32_NT" 来挑 CRC 工具:
#   MINGW32_NT/CYGWIN -> tools/crc_binary/encrypt.exe   (Windows)
#   Darwin            -> encrypt.darwin
#   其它              -> encrypt  (Linux ELF)
# 本环境 uname 是 MINGW64_NT-*，匹配不上，会去调 Linux 的 encrypt 而报
# "cannot execute binary file: Exec format error"。
# 这里直接把 ENCRYPT/ENCRYPT_ARGS 覆盖成 Windows 分支的取值（与厂商一致）。
"$MAKE" "ROOT_DIR=$SDKWIN" \
        "ENCRYPT=./tools/crc_binary/encrypt.exe" "ENCRYPT_ARGS=" \
        "$TARGET" > "$ROOT/work/build.log" 2>&1
RC=$?
echo "[build] exit=$RC   (完整日志: work/build.log)"
tail -40 "$ROOT/work/build.log"

if [ "$RC" -eq 0 ]; then
  echo "---- 产物 (out/) ----"
  ls -la out/ 2>/dev/null | head -20
fi
exit "$RC"
