# 小鲸灵学园 WhaleMaid 🐋

> **小鲸灵学园**:面向 10 岁儿童的 AI 学习/游玩 Agent(双身份:孩子空间 + 家长控制室)。入口:`web/frontend/index.html` 头像墙;隐私与数据见 docs/12;100 轮迭代见 docs/11。
> **小鲸灵摆件**:DeepSeek 鲸鱼娘 AI 语音桌面摆件——基于 [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) 二次开发，自建服务端，ESP32-S3 + DeepSeek API（旧陪伴版保留于 `web/frontend/legacy.html`）。

![status](https://img.shields.io/badge/status-Tier1_执行中-blue) ![license](https://img.shields.io/badge/model_license-CC_BY_NC_SA_4.0-red)

## 项目概览

「小鲸灵」是 DeepSeek 官方鲸鱼娘形象的 AI 语音摆件：摸头/摸肚有反应、叫「小爱同学」唤醒、说话傲娇嘴甜（管你叫「冉冉姐姐」）、断网时撒娇、低电量求投喂（充电）。

```
ESP32-S3(N16R8) ──WiFi──► WSL2 自建 xiaozhi-esp32-server (Docker)
  ├ INMP441 麦克风            ├ ASR: SenseVoiceSmall (本地)
  ├ MAX98357A + 喇叭          ├ LLM: DeepSeek API
  ├ SSD1306 0.96" OLED        └ TTS: EdgeTTS → CosyVoice2 克隆 (Tier2)
  ├ 触摸×2 (头 GPIO47 / 肚 GPIO21)
  └ 18650 + TP4056 + 负载共享 (≈4~7h 续航)
```

## 目录结构

```
├── docs/                     # 全套工程文档（开工前按序读）
│   ├── 00_版本台账.md         # 版本 pin / 硬规则 / 待实机确认清单
│   ├── 01_采购清单.md         # BOM ¥141~266 + 采购红线
│   ├── 02_接线烧录手册.md     # 接线表 / 上电三红线 / 台架 8 步 / whale-maid 板目录全码
│   ├── 03_服务端部署手册.md   # WSL2 Docker 部署 / 鲸鱼娘 prompt / OTA 对接
│   ├── 04_外壳流水线.md       # 3MF 解剖结论 / Blender 挖腔流 / 打印参数卡
│   ├── 05_功耗预算表.md       # 续航测算 / 验收门
│   ├── 06_彩蛋台词.md         # 20 句人设台词 + ogg 制作流水线
│   └── 3mf_anatomy_report.json
├── scripts/
│   └── analyze_3mf.py        # 3MF 几何解剖脚本（纯 stdlib，可复跑）
└── src/                      # 双仓 pin（本地开发用，不入 git）
    ├── xiaozhi-esp32/        # v2.6.0 (4de00ae)
    └── xiaozhi-esp32-server/ # v0.9.8 (tarball)
```

## 路线图

| Tier | 内容 | 状态 |
|---|---|---|
| 1 | 采购 → 台架 bring-up → whale-maid 板固件 → 服务端 → 端到端对话 | 🔄 冲刺中:源码/板 patch/服务端配置/网页保底就位,等零件与编译验证(**生日线 11-27**,见 docs/07) |
| 2 | 外壳打印装配 + 脸部方案拍板 + 彩蛋 20 句 | ⏳ 彩蛋 v2(冉冉姐姐版)已预生成 |
| 3 | CosyVoice2 音色克隆 + 公网送人（cf-tunnel） | ⏳ |

## 授权与致谢

- 3D 模型：[MakerWorld 2899554](https://makerworld.com/models/2899554) by lucyundead，**CC BY-NC-SA 4.0**
- 形象授权链：溟月（原作，上善无形）→ 女仆装二创 ZipZipPipe → 3D 化 lucyundead
- **本项目仅限个人学习/自用/送人，禁止商用；再分发须同协议署名**
- 固件基座 [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)（MIT）、服务端 [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server)，感谢上游
