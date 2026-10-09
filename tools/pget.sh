#!/usr/bin/env bash
# pget.sh —— 通用多线程分段下载器（用于慢速/大文件）
# 用法: pget.sh <url> <outfile> [nparts] [total_bytes]
# 说明: 依赖 curl 的 Range 支持；先 HEAD 取总长，再按块并发拉取后拼接校验。
set -u
URL="$1"; OUT="$2"; N="${3:-8}"; TOTAL="${4:-0}"

if [ "$TOTAL" = "0" ] || [ -z "$TOTAL" ]; then
  TOTAL=$(curl -sIL -m 60 "$URL" | tr -d '\r' | awk 'tolower($1)=="content-length:"{v=$2} END{print v}')
fi
if [ -z "$TOTAL" ] || [ "$TOTAL" = "0" ]; then echo "cannot determine size"; exit 1; fi
echo "url=$URL"
echo "total=$TOTAL parts=$N"

WORK="${OUT}.parts"
rm -rf "$WORK"; mkdir -p "$WORK"
PART=$(( (TOTAL + N - 1) / N ))

get_one() {
  idx=$1; a=$2; b=$3
  want=$(( b - a + 1 ))
  for try in 1 2 3 4 5; do
    curl -s -L -m 1800 -r "${a}-${b}" -o "${PWORK}/p${idx}.bin" "${PURL}"
    sz=$(stat -c %s "${PWORK}/p${idx}.bin" 2>/dev/null || echo 0)
    [ "$sz" = "$want" ] && { echo "  p$idx OK"; return 0; }
    echo "  p$idx retry$try ($sz/$want)" >&2
    sleep 2
  done
  echo "  p$idx FAILED"
  return 1
}
# 注意: bash 子 shell 看不到未导出的变量/数组，这里用环境变量传递
export PURL="$URL" PWORK="$WORK"
export -f get_one

seq 0 $((N-1)) | while read i; do
  a=$(( i * PART )); b=$(( a + PART - 1 ))
  [ $b -gt $((TOTAL-1)) ] && b=$((TOTAL-1))
  echo "$i $a $b"
done > "$WORK/list.txt"

cat "$WORK/list.txt" | xargs -P "$N" -L 1 bash -c 'get_one $0 $1 $2'

rm -f "$OUT"
for i in $(seq 0 $((N-1))); do cat "$WORK/p${i}.bin" >> "$OUT"; done
FINAL=$(stat -c %s "$OUT" 2>/dev/null || echo 0)
echo "final=$FINAL expected=$TOTAL"
[ "$FINAL" = "$TOTAL" ] && { echo SIZE_OK; rm -rf "$WORK"; exit 0; } || { echo SIZE_MISMATCH; exit 1; }
