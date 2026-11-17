"""测试环境隔离(借鉴 MindVault:必须在导入 app 之前设定环境)。

- 强制离线模式:清掉 DEEPSEEK_API_KEY,offline 路由才能确定性断言
- 本套件不测 /api/tts(需要微软云网络),TTS 由浏览器 E2E 覆盖
"""
import os

# 赋空串而非 pop:_load_dotenv 用 setdefault 读 .env,不覆盖已有键——
# 这样即使本机 .env 有 key(或占位),测试也强制 offline 保持确定性
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["DEEPSEEK_MODEL"] = "deepseek-v4-flash"
