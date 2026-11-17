"""config/ 机器合同完整性测试(三端同步的防腐化闸门)。

口径:eggs_birthday.json 是网页前端离线兜底、TTS 生成脚本、固件触发映射的
唯一机器来源;persona/server_prompt/whalemaid.config.yaml 三处人设必须同步。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VALID_EMO = {"normal", "happy", "shy", "pouty", "sad", "sleepy"}
VALID_TAGS = {"开心", "害羞", "傲娇", "难过", "困"}


def _load(name):
    return (ROOT / name).read_text(encoding="utf-8")


def _eggs():
    return json.loads(_load("config/eggs_birthday.json"))


class TestEggsContract:
    def test_每个触发池非空且全为字符串(self):
        for pool, lines in _eggs()["triggers"].items():
            assert isinstance(lines, list) and lines, f"池 {pool} 为空"
            assert all(isinstance(x, str) and x.strip() for x in lines), f"池 {pool} 有空台词"

    def test_池名符合固件符号规范(self):
        """docs/06:小写字母+下划线(ogg 符号生成约束)。"""
        for pool in _eggs()["triggers"]:
            assert re.fullmatch(r"[a-z_]+", pool), f"池名 {pool} 含大写/非法字符"

    def test_emo键与池完全对齐(self):
        eggs = _eggs()
        assert set(eggs["emo"]) == set(eggs["triggers"]), "emo 映射与触发池不对齐"
        assert all(v in VALID_EMO for v in eggs["emo"].values()), "emo 值超出前端六态"

    def test_关键词路由指向存在的池(self):
        eggs = _eggs()
        for trigger in eggs["keyword_map"]:
            assert trigger in eggs["triggers"], f"keyword_map 指向不存在的池 {trigger}"

    def test_新增池有音频产物(self):
        """make_egg_audio.py 预生成的 mp3 应覆盖全部池(池_序号 命名)。"""
        mp3_dir = ROOT / "assets_audio" / "mp3"
        if not mp3_dir.exists():
            return  # 音频未生成的环境跳过
        eggs = _eggs()
        for pool, lines in eggs["triggers"].items():
            for i in range(1, len(lines) + 1):
                assert (mp3_dir / f"{pool}_{i}.mp3").exists(), f"缺音频 {pool}_{i}.mp3"


class TestPersonaSync:
    """人设单一来源纪律:三处引用必须与 persona.md 同步。"""

    def test_服务端prompt含冉冉姐姐与生日模式(self):
        prompt = _load("config/server_prompt.txt")
        assert "冉冉姐姐" in prompt and "生日" in prompt
        assert "1~2 句" in prompt  # 语音短回复约束

    def test_prompt表情标记与后端白名单一致(self):
        prompt = _load("config/server_prompt.txt")
        for tag in VALID_TAGS:
            assert f"({tag})" in prompt, f"prompt 缺表情标记 ({tag})"

    def test_whalemaid配置与server_prompt同步(self):
        """固件服务端覆盖配置的 prompt 段落须包含标准模式(大肥鱼)关键约束。"""
        yaml_text = _load("firmware/server/whalemaid.config.yaml")
        adult = _load("config/server_prompt_adult.txt")
        assert "鱼片" in yaml_text and "(开心)" in yaml_text and "(困)" in yaml_text
        assert "1~2 句" in yaml_text
        assert "(开心)" in adult  # 表情协议交叉确认

    def test_persona_md存在且为权威版(self):
        persona = _load("config/persona.md")
        assert "冉冉姐姐" in persona
        assert "单一来源" in persona

    def test_大人prompt存在且协议同步(self):
        adult = _load("config/server_prompt_adult.txt")
        assert "鱼片" in adult and "1~2 句" in adult
        for tag in VALID_TAGS:
            assert f"({tag})" in adult, f"大人 prompt 缺表情标记 ({tag})"
