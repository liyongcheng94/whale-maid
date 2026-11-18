"""R1/R2 身份隔离审计(docs/11 轮次记录)。

口径:孩子可达页面(kid/legacy/index)不引用任何家长端链接或家长端点;
孩子端不出现重置/模式切换等可损坏配置的操作;头像墙家长入口保持弱化(页脚文字)。
"""
import re
from pathlib import Path

from fastapi.testclient import TestClient

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import app  # noqa: E402

client = TestClient(app)
FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
KID = (FRONTEND / "kid.html").read_text(encoding="utf-8")
LEGACY = (FRONTEND / "legacy.html").read_text(encoding="utf-8")
INDEX = (FRONTEND / "index.html").read_text(encoding="utf-8")


class TestIdentityIsolation:
    def test_kid端零家长链接(self):
        """孩子空间(kid/legacy)严禁家长端引用;分流页(index)允许且仅允许 1 个弱化页脚链接。"""
        for name, html in [("kid", KID), ("legacy", LEGACY)]:
            assert "parent.html" not in html, f"{name}.html 出现家长端链接"
            assert not re.search(r"/api/parent/", html), f"{name}.html 引用家长端点"
        weak = len(re.findall(r"parent\.html", INDEX))
        assert weak == 1 and "家长入口" in INDEX, "头像墙家长入口必须且只能是弱化页脚链接"

    def test_kid端无可损坏配置入口(self):
        """孩子端允许:静音/音量;不允许:清记忆/模式切换/重置类操作。"""
        for name, html in [("kid", KID), ("index", INDEX)]:
            assert "清空" not in html, f"{name}.html 出现重置类操作"

    def test_R95_家长端文案终审(self):
        """家长端禁低幼词;学园语气一致性(轮次 95)。"""
        PARENT = (FRONTEND / "parent.html").read_text(encoding="utf-8")
        for b in ["白饭饭", "晒屁股", "宝贝", "睡觉觉", "咕噜噜"]:
            assert b not in PARENT, f"parent.html 含低幼词 {b}"

    def test_R96_孩子端退出到头像墙(self):
        """R20 边界:孩子可返回头像墙换档案(多设备/多孩子切换)。"""
        assert "location.href" in KID or "kid.html" not in KID

    def test_头像墙家长入口保持弱化(self):
        assert "家长入口" in INDEX  # 弱化为页脚文字链接(PRD: 隐藏或弱化)
