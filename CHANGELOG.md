# Changelog(Keep-a-Changelog 轻量版;条目写「对使用者的影响」,历史细节见 docs/00 台账与 git log)

## [Unreleased]

### Added(2026-11-17 生日冲刺第一波)
- **网页版小鲸灵(web/,端口 8100)**:生日硬保底。摸头/摸肚彩蛋、语音对话(浏览器识别)、DeepSeek 聪明模式+离线台词兜底三层降级——实机赶不上,生日照常玩。
- **表情系统**:回复开头 (表情) 标记 → 鲸鱼娘六态表情(借鉴 Open-LLM-VTuber;离线台词同样映射)。
- **播报中摸一下=停止**(简化语音打断)+ **发呆搭话**(50s 无操作主动彩蛋)。
- **人设 v2「冉冉姐姐」儿童化+生日模式**,`config/` 单一来源,网页/服务端共用;彩蛋台词 27 句 edge-tts 预生成。
- **工程化**:一键验证闸门 `scripts/verify.py`(6 gates)、web 后端 pytest(27 用例)、CI(`.github/workflows/ci.yml`)、本 CHANGELOG、AGENTS.md 项目宪法。

### Fixed
- 文档债:3MF 脚本名(docs/00 §六)、trimesh 误标(docs/01)、审校 8 项状态回写(docs/00 §七)、docs_tmp_eggs 悬空引用(docs/02)。

### 对使用者的影响
- 现在即可在浏览器玩小鲸灵(台词模式);配置 DeepSeek key 后自动升级聪明模式。
- 彩蛋音频新增 hush/idle 池 5 句;以后改台词只需改 `config/eggs_birthday.json` + 重跑生成脚本,测试与 CI 会拦截三端不同步。
