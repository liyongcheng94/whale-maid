"""学园身份隔离与 PIN 测试(docs/prd/xueyuan_prd_v1.md §0)。

口径:孩子端端点无鉴权;家长端点必须 X-Parent-Token(此处 query token,与前端一致);
PIN 服务端校验+5 次失败锁 15 分钟;profiles 多孩子+低龄锁定。
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402
import learn_routes  # noqa: E402
import store  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)


@pytest.fixture()
def fresh_pin(tmp_path, monkeypatch):
    """隔离 PIN 文件并清空 token 内存态。"""
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
    store._parent_tokens.clear()
    return tmp_path


class TestProfiles:
    def test_多孩子档案下发(self, fresh_pin):
        body = client.get("/api/profiles").json()
        ids = [c["id"] for c in body["children"]]
        assert "ranran" in ids and len(ids) >= 2
        locked = [c for c in body["children"] if c["locked"]]
        assert locked and all(c.get("lock_note") for c in locked)

    def test_低龄档案有锁定标记(self, fresh_pin):
        body = client.get("/api/profiles").json()
        baby = next(c for c in body["children"] if c["locked"])
        assert baby["age"] < 6


class TestPin:
    def test_未设置时verify报409(self, fresh_pin):
        r = client.post("/api/parent/pin/verify", json={"pin": "1234"})
        assert r.status_code == 409

    def test_非数字pin400(self, fresh_pin):
        assert client.post("/api/parent/pin/setup", json={"pin": "ab1"}).status_code == 400

    def test_设置并验证成功(self, fresh_pin):
        r = client.post("/api/parent/pin/setup", json={"pin": "888888"})
        assert r.status_code == 200 and r.json()["token"]
        r2 = client.post("/api/parent/pin/verify", json={"pin": "888888"})
        assert r2.status_code == 200 and r2.json()["token"]

    def test_重复设置409(self, fresh_pin):
        client.post("/api/parent/pin/setup", json={"pin": "888888"})
        assert client.post("/api/parent/pin/setup", json={"pin": "1234"}).status_code == 409

    def test_错5次锁定429(self, fresh_pin):
        client.post("/api/parent/pin/setup", json={"pin": "888888"})
        for _ in range(5):
            r = client.post("/api/parent/pin/verify", json={"pin": "0000"})
            assert r.status_code == 401
        r = client.post("/api/parent/pin/verify", json={"pin": "888888"})  # 对的也被锁
        assert r.status_code == 429


class TestIsolation:
    def test_家长端点无token401(self, fresh_pin):
        for path in ["/api/parent/overview", "/api/parent/preview/ranran"]:
            assert client.get(path, params={"token": ""}).status_code == 401
        assert client.get("/api/parent/check", params={"token": "fake"}).status_code == 401

    def test_有token可访问总览(self, fresh_pin):
        tok = client.post("/api/parent/pin/setup", json={"pin": "1234"}).json()["token"]
        r = client.get("/api/parent/overview", params={"token": tok})
        assert r.status_code == 200
        cards = r.json()["cards"]
        assert len(cards) >= 2 and all("summary" in c for c in cards)

    def test_孩子端端点无鉴权可用(self, fresh_pin):
        assert client.get("/api/learn/map", params={"child": "ranran"}).status_code == 200
        assert client.get("/api/profiles").status_code == 200
