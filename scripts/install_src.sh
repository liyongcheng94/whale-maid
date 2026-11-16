#!/usr/bin/env bash
# 拉取双仓源码并安装 whale-maid 板 patch
# 用法：在项目仓库根执行  bash scripts/install_src.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ESP32_REPO="https://github.com/78/xiaozhi-esp32"
ESP32_TAG="v2.6.0"
SERVER_REPO="https://github.com/xinnan-tech/xiaozhi-esp32-server"
SERVER_TAG="v0.9.8"

mkdir -p src

# ---------- 1. xiaozhi-esp32 @v2.6.0 + whale-maid patch ----------
if [ ! -d src/xiaozhi-esp32/.git ]; then
    echo ">>> 克隆 xiaozhi-esp32 ${ESP32_TAG} ..."
    # 网络不稳时浅克隆可能 early EOF，重试 3 次；仍失败用 tarball 降级
    ok=0
    for i in 1 2 3; do
        if git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=30 clone --depth 1 --branch "$ESP32_TAG" "$ESP32_REPO" src/xiaozhi-esp32; then ok=1; break; fi
        echo ">>> 第 ${i} 次克隆失败，重试..."
        rm -rf src/xiaozhi-esp32
    done
    if [ "$ok" != 1 ]; then
        echo ">>> git 克隆持续失败，降级 tarball（无 .git，改为解压后应用 patch）"
        curl -fL --retry 3 -o /tmp/xz32.tar.gz "https://github.com/78/xiaozhi-esp32/archive/refs/tags/${ESP32_TAG}.tar.gz"
        mkdir -p src/xiaozhi-esp32
        tar xzf /tmp/xz32.tar.gz -C src/xiaozhi-esp32 --strip-components=1
        echo ">>> tarball 模式：直接应用 patch"
        cd src/xiaozhi-esp32
        patch -p1 < "$ROOT/firmware/patches/0001-whale-maid-board.patch"
        cd "$ROOT"
        echo ">>> 完成（tarball 模式，无 git 历史）。"
        exit 0
    fi
fi

cd src/xiaozhi-esp32
echo ">>> 当前 commit: $(git log --oneline -1)"
git describe --tags --exact-match 2>/dev/null | grep -q "$ESP32_TAG" || echo "!! 警告：不在 ${ESP32_TAG} 上"
if ! git rev-parse --verify -q whale-maid >/dev/null; then
    git checkout -q -b whale-maid
fi
echo ">>> 应用 whale-maid 板 patch ..."
git apply --check "$ROOT/firmware/patches/0001-whale-maid-board.patch" 2>/dev/null \
  && git apply "$ROOT/firmware/patches/0001-whale-maid-board.patch" \
  || echo ">>> patch 已应用过或冲突（检查 main/boards/whale-maid 是否存在）"
cd "$ROOT"

# ---------- 2. xiaozhi-esp32-server @v0.9.8 ----------
if [ ! -d src/xiaozhi-esp32-server/main/xiaozhi-server ]; then
    echo ">>> 获取 xiaozhi-esp32-server ${SERVER_TAG} ..."
    ok=0
    for i in 1 2 3; do
        if git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=30 clone --depth 1 --branch "$SERVER_TAG" "$SERVER_REPO" src/xiaozhi-esp32-server; then ok=1; break; fi
        echo ">>> 第 ${i} 次克隆失败，重试..."
        rm -rf src/xiaozhi-esp32-server
    done
    if [ "$ok" != 1 ]; then
        echo ">>> git 持续失败，降级 tarball"
        curl -fL --retry 3 -o /tmp/xzserver.tar.gz "https://github.com/xinnan-tech/xiaozhi-esp32-server/archive/refs/tags/${SERVER_TAG}.tar.gz"
        mkdir -p src/xiaozhi-esp32-server
        tar xzf /tmp/xzserver.tar.gz -C src/xiaozhi-esp32-server --strip-components=1
    fi
fi
echo ">>> server 就位：$(ls src/xiaozhi-esp32-server/main/xiaozhi-server/config.yaml >/dev/null 2>&1 && echo config.yaml OK || echo 异常)"

echo ""
echo "全部完成。下一步："
echo "  1. source ~/esp-idf/export.sh && cd src/xiaozhi-esp32"
echo "  2. python scripts/build.py whale-maid --language zh-CN --wake-word wn9_xiaoaitongxue"
echo "  3. 服务端：见 firmware/server/README.md"
