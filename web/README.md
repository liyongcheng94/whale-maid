# web/ · 小鲸灵网页版(生日保底 + 人设调试台)

生日硬保底:浏览器打开即玩,不依赖实机、不依赖 Docker。
人设单一来源:`config/persona.md`;台词包:`config/eggs_birthday.json`(网页离线兜底 + 彩蛋 TTS 生成共用,由 `/api/eggs` 下发,前端零硬编码)。

## 快速开始(家里 Windows,纯 Python)

```powershell
cd web\backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 可选:配置 DeepSeek(不配则纯离线台词模式,照样可玩;key 别提交进 git)
set DEEPSEEK_API_KEY=sk-xxx        # 或写入 web\backend\.env(KEY=VALUE)

uvicorn main:app --host 0.0.0.0 --port 8100
```

打开 http://localhost:8100(局域网内平板可访问 http://<家里PC IP>:8100)。

## 功能

| 功能 | 说明 |
|---|---|
| 摸头/摸肚 | 页面热区点击 → 随机彩蛋 + 动画 + 粒子;音频走预生成缓存**零延迟** |
| 情绪韵律 | 表情驱动 TTS 语速/音调:开心快而亮、困困慢而低 |
| 多轮记忆 | 最近 8 轮滑动窗口,按天分段;离线回复也入记忆 |
| 语音对话 | 🎤 按住说话(浏览器 SpeechRecognition zh-CN)→ /api/chat → TTS 播报 |
| 文字兜底 | 输入框 + 快捷 chips(再讲一个/生日快乐/唱歌/故事/白饭) |
| 🤫 / 🔊 / ⛶ | 专属停止按钮;静音(localStorage 持久化);全屏(平板沉浸) |
| DeepSeek | 有 key → 聪明模式;无 key/超时/断网 → 离线台词包,状态 chip 实时显示 |
| TTS 降级链 | 预生成音频 → edge-tts(后端)→ 浏览器 speechSynthesis → 仅文字气泡 |
| 生日模式 | 11-27 自动横幅+彩带彩蛋;调试用 `?force=1` 预览;`?idle=毫秒` 调发呆间隔 |
| 对话日志 | `data/chat_log.jsonl` 本地落盘:家长可查 + 排障,不上传 |

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| DEEPSEEK_API_KEY | 空 | 配置后启用聪明模式 |
| DEEPSEEK_MODEL | deepseek-chat | 以 DeepSeek 官方为准改这里 |
| WHALE_TTS_VOICE | zh-CN-XiaoyiNeural | 晓伊(活泼女声);可换 zh-CN-XiaoxiaoNeural |

## 端口

8100(避开服务端 8000/8003)。生产映射给平板用 `--host 0.0.0.0` + Windows 防火墙放行 8100。
