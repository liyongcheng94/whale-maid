"""R44 改名端点测试:token 保护/长度校验/写回 profiles.json。"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import learn_routes  # noqa: E402
import store  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)


@pytest.fixture()
def tok(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(learn_routes.store, "DATA", tmp_path)
    return client.post("/api/parent/pin/setup", json={"pin": "9090"}).json()["token"]


def test_改名写回档案(tok, tmp_path, monkeypatch):
    monkeypatch.setattr(learn_routes, "PROFILES_PATH", tmp_path / "profiles.json")
    import shutil
    shutil.copy(r"D:\project\whale-maid\config\profiles.json", tmp_path / "profiles.json")
    r = client.put("/api/parent/profile", params={"token": tok},
                   json={"child_id": "ranran", "name": "冉冉酱"})
    assert r.status_code == 200
    prof = json.loads((tmp_path / "profiles.json").read_text(encoding="utf-8"))
    assert next(c for c in prof["children"] if c["id"] == "ranran")["name"] == "冉冉酱"


def test_空名字400(tok):
    assert client.put("/api/parent/profile", params={"token": tok},
                      json={"child_id": "ranran", "name": "  "}).status_code == 400


def test_未知名404(tok):
    assert client.put("/api/parent/profile", params={"token": tok},
                      json={"child_id": "ghost", "name": "x"}).status_code == 404


def test_无token401(tok):
    assert client.put("/api/parent/profile", params={"token": ""},
                      json={"child_id": "ranran", "name": "x"}).status_code == 401
