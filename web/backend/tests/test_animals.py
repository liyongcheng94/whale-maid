"""R6 猜动物测试(docs/10)。

口径:开局给线索 1;猜错自动放下一条线索(1→2→3);「提示/下一条」手动放;
3 条后仍不中揭晓;猜中清局;线索音频逐条预生成。
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402
from main import ANIMALS, ANIMAL_GAMES, app  # noqa: E402

client = TestClient(app)
SID = "animal-test"


@pytest.fixture(autouse=True)
def clean():
    ANIMAL_GAMES.clear()
    yield
    ANIMAL_GAMES.clear()


class TestAnimalsContract:
    def test_数量与线索结构(self):
        assert len(ANIMALS) >= 8
        for a in ANIMALS:
            assert a["id"].isascii() and a["id"].islower()
            assert len(a["clues"]) == 3 and a["name"] and a["alias"]

    def test_线索音频预生成(self):
        mp3 = Path(__file__).resolve().parents[3] / "assets_audio" / "mp3"
        if not mp3.exists():
            pytest.skip("音频未生成的环境")
        for a in ANIMALS:
            for n in (1, 2, 3):
                assert (mp3 / f"animals_{a['id']}_{n}.mp3").exists()


class TestAnimalGame:
    def _start(self):
        return client.post("/api/chat", json={"text": "我们来玩猜动物游戏", "session_id": SID}).json()

    def test_开局给线索1(self):
        body = self._start()
        assert body["pool"] == "animal_start"
        assert body["animal"]["clue_no"] == 1 and body["clue_audio"].endswith("_1")
        assert ANIMAL_GAMES[SID]["clue"] == 1

    def test_猜错自动进线索2(self):
        self._start()
        aid = ANIMAL_GAMES[SID]["id"]
        wrong = next(a["alias"][0] for a in ANIMALS if a["id"] != aid)
        body = client.post("/api/chat", json={"text": wrong, "session_id": SID}).json()
        assert body["animal"]["clue_no"] == 2 and ANIMAL_GAMES[SID]["clue"] == 2

    def test_猜错两次后揭晓(self):
        self._start()
        aid = ANIMAL_GAMES[SID]["id"]
        wrong = next(a["alias"][0] for a in ANIMALS if a["id"] != aid)
        client.post("/api/chat", json={"text": wrong, "session_id": SID}).json()
        client.post("/api/chat", json={"text": "线索" , "session_id": SID}).json()
        body = client.post("/api/chat", json={"text": wrong, "session_id": SID}).json()
        assert body["pool"] == "animal_reveal" and SID not in ANIMAL_GAMES

    def test_猜中清局(self):
        self._start()
        aid = ANIMAL_GAMES[SID]["id"]
        name = next(a["name"] for a in ANIMALS if a["id"] == aid)
        body = client.post("/api/chat", json={"text": name, "session_id": SID}).json()
        assert body["pool"] == "animal_right" and SID not in ANIMAL_GAMES

    def test_退出揭晓(self):
        self._start()
        aid = ANIMAL_GAMES[SID]["id"]
        name = next(a["name"] for a in ANIMALS if a["id"] == aid)
        body = client.post("/api/chat", json={"text": "不猜了", "session_id": SID}).json()
        assert body["pool"] == "animal_reveal" and name in body["reply"]
