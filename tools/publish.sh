# tools/publish.sh —— V1.0.0 一键发布（凭据从环境变量读，不落盘）
#
# 用法（Git Bash）：
#   export GH_TOKEN=ghp_你的令牌
#   bash tools/publish.sh
#
# 它会依次完成：
#   1. 创建GitHub 公开仓库 sparkleiot/bk7238-at-esp32c3-compat（已存在则跳过）
#   2. push main 分支
#   3. push v1.0.0 标签
#   4. 创建 Release，附上固件与 Release 正文
#   5. 回读校验并在最后unset 掉凭据
set -euo pipefail

cd "$(dirname "$0")/.."

PY="C:/Users/99471/.workbuddy/binaries/python/versions/3.13.12/python.exe"
OWNER="${OWNER:-sparkleiot}"
REPO="${REPO:-bk7238-at-esp32c3-compat}"
TAG="${TAG:-v1.0.0}"
FW="firmware/at-esp32c3-compat_2M.1220.bin"

if [ -z "${GH_TOKEN:-}" ]; then
  echo "[FAIL] 请先设置：export GH_TOKEN=ghp_你的令牌" >&2
  exit 1
fi
if [ ! -f "$FW" ]; then
  echo "[FAIL] 找不到固件 $FW —— 先跑 bash tools/build.sh" >&2
  exit 1
fi

echo "=== 发布前自检 ==="
"$PY" tools/scrub_public_identifiers.py --check
"$PY" tools/check_modified_sync.py | tail -1
"$PY" tools/verify_patch.py | tail -1

echo
echo "=== 发布 ==="
"$PY" tools/gh_publish.py \
  --owner "$OWNER" \
  --repo "$REPO" \
  --tag "$TAG" \
  --release-name "$TAG —— ESP32-C3 / ESP-AT 兼容 AT 固件（首个对外发布版本）" \
  --release-body "docs/RELEASE_V1.0.0.md" \
  --asset "$FW" \
  --asset firmware/at-esp32c3-compat.bin

RC=$?
unset GH_TOKEN
echo
echo "=== 凭据已从当前 shell 清除 ==="
exit $RC