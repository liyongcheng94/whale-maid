"""测试环境隔离(借鉴 MindVault:必须在导入 app 之前设定环境)。

- 强制离线模式:清掉 DEEPSEEK_API_KEY,offline 路由才能确定性断言
- 本套件不测 /api/tts(需要微软云网络),TTS 由浏览器 E2E 覆盖
"""
import os

os.environ.pop("DEEPSEEK_API_KEY", None)
os.environ["DEEPSEEK_MODEL"] = "deepseek-chat"
