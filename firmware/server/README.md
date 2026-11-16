# 服务端部署快照（xiaozhi-esp32-server v0.9.8）

> 权威文档：上游 docs/Deployment.md。本快照只记录我们环境（WSL2 mirrored / Win11）的差异步骤，完整步骤见项目仓库 `docs/03_服务端部署手册.md`。

## 快速开始（前提：src/ 仓已就位，见 scripts/install_src.sh）

```bash
cd src/xiaozhi-esp32-server/main/xiaozhi-server

# 1. 下载 SenseVoiceSmall 模型（~1GB，必须独立下载）
#    https://modelscope.cn/models/iic/SenseVoiceSmall/resolve/master/model.pt
mkdir -p models/SenseVoiceSmall data
# 放入 model.pt

# 2. 覆盖配置（不碰上游 config.yaml）
#    拷贝 firmware/server/whalemaid.config.yaml 到 data/.config.yaml，
#    改两处：<PC局域网IP> 与 DeepSeek api_key

# 3. 起容器
docker compose up -d
docker compose logs -f | grep -E "OTA|Websocket"
```

成功标志：
```
OTA接口是        http://<PC局域网IP>:8003/xiaozhi/ota/
Websocket地址是  ws://<PC局域网IP>:8000/xiaozhi/v1/
```

## Windows 侧（mirrored 模式）

- 防火墙放行：`New-NetFirewallRule -DisplayName "xiaozhi-server" -Direction Inbound -LocalPort 8000,8003 -Protocol TCP -Action Allow`
- PC 从不睡眠；docker restart: always 已在上游 compose 中

## 默认模块链（v0.9.8 实测）

VAD=SileroVAD / ASR=FunASR(SenseVoiceSmall 本地) / LLM=ChatGLMLLM(默认) → 我们改 DeepSeekLLM / TTS=EdgeTTS / Memory=nomem

p3 格式说明：p3 是服务端侧音乐目录/TTS 缓存的高效格式（4字节头+Opus 包），由 server 解码为 opus 帧下发；固件侧音效走 ogg 编译期嵌入，与 p3 无关。
