#!/usr/bin/env bash
# ============================================================
# 小鲸灵 · 固件仓库统一同步脚本
# 用法：在 WSL 内执行  bash ~/project/小鲸灵/scripts/sync_firmware.sh
#
# 仓库拓扑（以 fork 为唯一事实源）：
#   src/xiaozhi-esp32   固件基座（构建用完整源码树）
#     ├── origin = 78/xiaozhi-esp32（上游，只读）
#     ├── fork   = liyongcheng94/whale-maid（事实源，只读拉取）
#     └── whale-maid 分支 = 上游 main + 板级提交（可多个）
#   src/whale-maid      权威 monorepo（web/docs/config）
#     └── firmware/patches/ 由本脚本从基座自动回写生成
#
# 流向：上游更新 → 基座 rebase → 回写 patch → 你在 fork 里 commit+push
# ============================================================
set -euo pipefail

PROJ="$(cd "$(dirname "$0")/.." && pwd)"
BASE="$PROJ/src/xiaozhi-esp32"
MONO="$PROJ/src/whale-maid"

step() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }

step "1/5 拉取上游与 fork"
cd "$BASE"
git fetch origin main --tags --quiet
git fetch fork --quiet
UP="$(git rev-parse origin/main)"
echo "上游 tip: $UP  ($(git log -1 --format='%s' "$UP"))"

step "2/5 基座 whale-maid 分支对齐上游（rebase）"
BEHIND=$(git rev-list --count whale-maid.."origin/main")
if [ "$BEHIND" -gt 0 ]; then
  echo "落后 $BEHIND 个提交，rebase 中..."
  git rebase origin/main
else
  echo "基座已与上游同步，无需 rebase"
fi

step "3/5 校验板级提交数量"
N=$(git rev-list --count origin/main..whale-maid)
echo "板级提交数: $N"
if [ "$N" -eq 0 ]; then
  echo "⚠ whale-maid 分支上没有板级提交——无内容可回写，退出"
  exit 0
fi
if [ "$N" -gt 1 ]; then
  echo "⚠ 超过 1 个板级提交：脚本将生成 $N 个 patch（0001~000N），确认 fork 的 CI 仍按 patches/ 顺序应用"
fi

step "4/5 回写 patch 到权威仓库"
PATCH_DIR="$MONO/firmware/patches"
mkdir -p "$PATCH_DIR"
rm -f "$PATCH_DIR"/[0-9]*.patch
git format-patch "origin/main..whale-maid" -o "$PATCH_DIR" --quiet
ls -1 "$PATCH_DIR"/*.patch | while read -r f; do echo "  生成: $(basename "$f")"; done

step "4.5/5 回写前自验闸门（patch 套在上游基线必须还原出 whale-maid 树）"
export GIT_INDEX_FILE="$(mktemp -u)"
git read-tree origin/main
git apply --cached "$PATCH_DIR"/*.patch
T_PATCH="$(git write-tree)"
T_REAL="$(git rev-parse whale-maid^{tree})"
unset GIT_INDEX_FILE
if [ "$T_PATCH" = "$T_REAL" ]; then
  echo "✅ 自验通过: patch 树 $T_PATCH ≡ whale-maid 树 $T_REAL"
else
  echo "❌ 自验失败: patch 树 $T_PATCH ≠ whale-maid 树 $T_REAL —— 不回写，人工排查"
  exit 1
fi

step "5/5 完成状态"
cd "$MONO"
if [ -n "$(git status --porcelain firmware/patches)" ]; then
  echo "⚠ patch 有更新，待你在 whale-maid 仓库提交："
  git status --short firmware/patches
  echo "  建议: cd $MONO && git add firmware/patches && git commit -m 'chore(firmware): 同步板级 patch @ $(cd "$BASE" && git rev-parse --short whale-maid)' && git push"
else
  echo "patch 与权威仓库一致，无需提交"
fi
echo ""
echo "绿状态建议打 tag（任务书纪律）：cd $BASE && git tag whale-maid-$(date +%Y%m%d)-green && git push fork whale-maid-$(date +%Y%m%d)-green  # push 需你本机 SSH key"
