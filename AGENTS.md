# AGENTS.md · whale-maid 项目宪法(人和 AI 的唯一入口)

> 本文是仓库的**订单+地图**。任何文档与本文件冲突时:执行事实以 `docs/00_版本台账.md` 为准,工作流以本文件为准。
> 另一份指针文件 `CLAUDE.md` 只指到这里,勿在其内重复维护内容。

## 一、这是什么

**小鲸灵(whale-maid)**:DeepSeek 鲸鱼娘 AI 语音桌面摆件。ESP32-S3 实体玩具 + 自建服务端 + 网页版保底。
**当前硬 deadline:2026-11-27 = 冉冉的生日**。作战地图与排期见 `docs/07_生日冲刺行动单.md`。

## 二、仓库地图(每个目录一句话)

```
docs/            00 台账(事实唯一来源) + 01~07 分层执行文档 + 07 是当前 sprint 行动单
config/          人设机器合同(persona.md / eggs_birthday.json / server_prompt.txt)——网页与固件服务端共用,改人设只改这里
firmware/        patches/ 板代码 patch(权威,由 install_src.sh 应用到 src/) + server/ 服务端配置样例
scripts/         analyze_3mf.py(3MF 解剖) · make_egg_audio.py(彩蛋 TTS 预生成) · install_src.sh(拉源码) · verify.py(一键验证闸门)
web/             网页版小鲸灵(生日保底+人设调试台):FastAPI 后端 + 无构建单页前端
src/             双上游仓(xiaozhi-esp32 v2.6.0 + xiaozhi-esp32-server v0.9.8),gitignore 不入库
assets_audio/    彩蛋音频产物(mp3/wav),gitignore 不入库
```

## 三、常用命令

```bash
bash scripts/install_src.sh              # 克隆双上游 + 应用板 patch(网络差自动降级 tarball)
python scripts/verify.py                 # ★ 一键验证闸门(CI 与本地同一套,6 gates)
python scripts/make_egg_audio.py         # 彩蛋台词 → TTS 音频(改 config/eggs_birthday.json 后重跑)
cd web/backend && pip install -r requirements.txt -r requirements-dev.txt
cd web/backend && python -m pytest       # web 后端测试
cd web/backend && uvicorn main:app --port 8100   # 起网页版(见 web/README.md)
# 服务端部署/固件编译:见 docs/03 与 docs/02(等家里 WSL2+Docker / ESP-IDF 就绪)
```

## 四、硬规则(违反=事故)

1. **台账纪律**:任何版本/引脚/路径变更,先改 `docs/00_版本台账.md` 再改下游文档。
2. **OTA 变砖红线**:禁止修改 bread-compact-wifi 板引脚;whale-maid 板身份独立,patch 不碰原板文件(verify.py 的 patch 闸门会拦)。
3. **人设单一来源**:改人设/台词只改 `config/`,三处引用(server_prompt/whalemaid.config.yaml/网页前端)由测试与 verify 闸门强制同步。
4. **不手改生成物**:`lang_config.h`、`build/`、`sdkconfig*`;彩蛋音频产物由脚本生成不手改。
5. **铜箔不直连 GPIO47/21**(必须 TTP223);上电三红线见 docs/02 首页。
6. **密钥**:只进 `web/backend/.env`(gitignored)与部署时服务端配置;不进 git、不进文档、不发群。
7. **提交纪律**:小步提交、每层验证闸门绿了再提交;完成条件/禁区/回滚/接管点四件套见 docs/07。

## 五、验证闸门表(verify.py + CI)

| 闸门 | 检查内容 | 对应实现 |
|---|---|---|
| docs | md 引用的仓库内文件存在(防悬空引用) | scripts/verify.py gate_docs |
| patch | 板 patch 四件套+注册标记齐全,不碰原板 | gate_patch |
| config | 彩蛋池/emo 对齐/三处人设同步 | gate_config(与 tests/test_eggs.py 同口径) |
| audio | 彩蛋 mp3 覆盖全部池 | gate_audio |
| web | 后端可编译+前端关键标记 | gate_web |
| tests | web/backend pytest | gate_tests(CI 实跑) |

CI:`.github/workflows/ci.yml` — verify 全闸门 + pytest。**改 docs 也要过 CI**(文档闸门永远跑)。

## 六、AI 协作纪律

- 会话先对齐现状:git log + docs/07 排期表 + `python scripts/verify.py`。
- 改代码必须同提交更新对应文档(docs/00 台账或所属执行文档)——ownership rule。
- 测试口径写进测试 docstring(借鉴 quant-lab:测试即规格)。
- 硬件物理动作(下单/接线/烧录/装配)永远属于人,AI 只做软件与陪跑清单(docs/02 台架 8 步)。
