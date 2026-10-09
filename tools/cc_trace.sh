#!/bin/sh
# cc_trace.sh —— 包一层 gcc, 把它实际收到的每个参数逐行写入 $CC_TRACE, 便于诊断
{
  echo "=== INVOKE (argc=$#) ==="
  i=0
  for a in "$@"; do
    echo "ARG[$i]<<$a>>"
    i=$((i + 1))
  done
  echo "=== END ==="
} >> "$CC_TRACE" 2>&1

exec "C:/Users/99471/Desktop/BK7238_AT/sdk/toolchain/gcc-arm-none-eabi-10.3-2021.10/bin/arm-none-eabi-gcc.exe" "$@"
