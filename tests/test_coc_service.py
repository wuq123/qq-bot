from io import BytesIO
from pathlib import Path
from urllib import error, request

import pytest

from qqbot_app.coc_service import (
    CocService,
    CocTranslations,
    format_capital_raid_summary,
    format_clan_war_summary,
    format_player_battlelog_summary,
    format_player_league_history_summary,
    format_player_summary,
    normalize_player_tag,
    parse_coc_command,
)


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_normalize_player_tag_adds_hash_and_uppercases() -> None:
    assert normalize_player_tag(" abc ") == "#ABC"
    assert normalize_player_tag("#abc") == "#ABC"


def test_normalize_player_tag_rejects_invalid_value() -> None:
    with pytest.raises(ValueError, match="玩家标签格式不正确"):
        normalize_player_tag("#ABC!")


def test_parse_coc_command() -> None:
    command = parse_coc_command("查询玩家：#ABC123")

    assert command is not None
    assert command.action == "player"
    assert command.player_tag == "#ABC123"


def test_parse_building_time_command() -> None:
    command = parse_coc_command("查询建筑剩余时间：#ABC123")

    assert command is not None
    assert command.action == "building_time"
    assert command.player_tag == "#ABC123"


@pytest.mark.parametrize(
    ("text", "action"),
    [
        ("查询部落战：#CLAN1", "clan_war"),
        ("查询都城突袭：#CLAN1", "capital_raid"),
        ("查询玩家战斗日志：#PLAYER1", "battlelog"),
        ("查询玩家联赛历史：#PLAYER1", "league_history"),
    ],
)
def test_parse_extra_coc_commands(text: str, action: str) -> None:
    command = parse_coc_command(text)

    assert command is not None
    assert command.action == action


def test_parse_invalid_coc_command() -> None:
    command = parse_coc_command("查询玩家 #ABC123")

    assert command is not None
    assert command.action == "invalid"


def test_parse_invalid_building_time_command() -> None:
    command = parse_coc_command("查询建筑剩余时间 #ABC123")

    assert command is not None
    assert command.action == "invalid"


def test_get_player_summary_success(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def fake_urlopen(req: request.Request, timeout: int) -> _Response:
        seen["url"] = req.full_url
        seen["authorization"] = req.get_header("Authorization")
        seen["timeout"] = timeout
        return _Response(
            b'{"name":"Alice","tag":"#ABC","expLevel":100,"townHallLevel":13,'
            b'"trophies":5000,"bestTrophies":5500,"warStars":900,'
            b'"donations":120,"donationsReceived":80,"clan":{"name":"Clan A"},'
            b'"heroes":[{"name":"Barbarian King","level":80,"maxLevel":95,"village":"HOME_VILLAGE"}],'
            b'"spells":[{"name":"Lightning Spell","level":10,"maxLevel":11,"village":"HOME_VILLAGE"}],'
            b'"troops":[{"name":"Barbarian","level":11,"maxLevel":12,"village":"HOME_VILLAGE"}],'
            b'"heroEquipment":[{"name":"Earthquake Boots","level":18,"maxLevel":27,"village":"HOME_VILLAGE"}]}'
        )

    monkeypatch.setattr("qqbot_app.coc_service.request.urlopen", fake_urlopen)

    answer = CocService("token", timeout=3).get_player_summary("#ABC")

    assert seen["url"].endswith("/players/%23ABC")
    assert seen["authorization"] == "Bearer token"
    assert seen["timeout"] == 3
    assert "名称：Alice" in answer
    assert "部落：Clan A" in answer
    assert "- Barbarian King 80/95（主村）" in answer
    assert "- Lightning Spell 10/11（主村）" in answer
    assert "- Barbarian 11/12（主村）" in answer
    assert "- Earthquake Boots 18/27（主村）" in answer


@pytest.mark.parametrize(
    ("method_name", "input_tag", "expected_path"),
    [
        ("get_clan_war_summary", "#CLAN", "/clans/%23CLAN/currentwar"),
        ("get_capital_raid_summary", "#CLAN", "/clans/%23CLAN/capitalraidseasons?limit=1"),
        ("get_player_battlelog_summary", "#PLAYER", "/players/%23PLAYER/battlelog"),
        ("get_player_league_history_summary", "#PLAYER", "/players/%23PLAYER/leaguehistory"),
    ],
)
def test_extra_coc_queries_call_expected_endpoint(
    monkeypatch: pytest.MonkeyPatch, method_name: str, input_tag: str, expected_path: str
) -> None:
    seen = {}

    def fake_urlopen(req: request.Request, timeout: int) -> _Response:
        seen["url"] = req.full_url
        return _Response(b'{"items":[]}')

    monkeypatch.setattr("qqbot_app.coc_service.request.urlopen", fake_urlopen)

    answer = getattr(CocService("token"), method_name)(input_tag)

    assert seen["url"].endswith(expected_path)
    assert answer


def test_get_player_summary_translates_item_names(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    translations_path = tmp_path / "coc_translations.yaml"
    translations_path.write_text(
        "names:\n  Barbarian King: 野蛮人之王\n  Lightning Spell: 雷电法术\n  Barbarian: 野蛮人\n  Earthquake Boots: 地震靴\n",
        encoding="utf-8",
    )

    def fake_urlopen(req: request.Request, timeout: int) -> _Response:
        return _Response(
            b'{"name":"Alice","tag":"#ABC",'
            b'"heroes":[{"name":"Barbarian King","level":80,"maxLevel":95,"village":"HOME_VILLAGE"}],'
            b'"spells":[{"name":"Lightning Spell","level":10,"maxLevel":11,"village":"HOME_VILLAGE"}],'
            b'"troops":[{"name":"Barbarian","level":11,"maxLevel":12,"village":"HOME_VILLAGE"}],'
            b'"heroEquipment":[{"name":"Earthquake Boots","level":18,"maxLevel":27,"village":"HOME_VILLAGE"}]}'
        )

    monkeypatch.setattr("qqbot_app.coc_service.request.urlopen", fake_urlopen)

    answer = CocService("token", translations_path=str(translations_path)).get_player_summary("#ABC")

    assert "- 野蛮人之王 80/95（主村）" in answer
    assert "- 雷电法术 10/11（主村）" in answer
    assert "- 野蛮人 11/12（主村）" in answer
    assert "- 地震靴 18/27（主村）" in answer


def test_get_player_summary_without_token() -> None:
    answer = CocService("").get_player_summary("#ABC")

    assert answer == "未配置 COC_API_TOKEN，暂时无法查询部落冲突玩家。"


def test_get_building_time_summary_returns_official_api_limit() -> None:
    answer = CocService("").get_building_time_summary("#ABC")

    assert answer == "暂时无法查询建筑剩余时间：Clash of Clans 官方 API 不返回建筑列表、建筑等级或升级结束时间。"


def test_get_building_time_summary_validates_player_tag() -> None:
    answer = CocService("").get_building_time_summary("#ABC!")

    assert answer == "玩家标签格式不正确。"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (403, "部落冲突 API 拒绝访问"),
        (404, "未找到该部落冲突玩家"),
        (429, "请求过于频繁"),
        (503, "正在维护"),
        (500, "状态码 500"),
    ],
)
def test_get_player_summary_http_errors(monkeypatch: pytest.MonkeyPatch, status: int, expected: str) -> None:
    def fake_urlopen(req: request.Request, timeout: int) -> _Response:
        raise error.HTTPError(req.full_url, status, "error", {}, BytesIO())

    monkeypatch.setattr("qqbot_app.coc_service.request.urlopen", fake_urlopen)

    answer = CocService("token").get_player_summary("#ABC")

    assert expected in answer


def test_get_player_summary_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: request.Request, timeout: int) -> _Response:
        raise error.URLError("network")

    monkeypatch.setattr("qqbot_app.coc_service.request.urlopen", fake_urlopen)

    answer = CocService("token").get_player_summary("#ABC")

    assert answer == "查询部落冲突玩家失败，请检查网络或稍后重试。"


def test_format_player_summary_without_clan() -> None:
    answer = format_player_summary({"name": "Bob", "tag": "#ABC"})

    assert "部落：无" in answer
    assert "英雄：无" in answer
    assert "法术：无" in answer
    assert "兵种：无" in answer
    assert "装备：无" in answer


def test_format_clan_war_summary() -> None:
    answer = format_clan_war_summary(
        {
            "state": "inWar",
            "teamSize": 15,
            "attacksPerMember": 2,
            "startTime": "20260910T100000.000Z",
            "endTime": "20260911T100000.000Z",
            "clan": {"name": "我方", "stars": 20, "destructionPercentage": 80.5, "attacks": 18},
            "opponent": {"name": "对手", "stars": 19, "destructionPercentage": 79.1, "attacks": 17},
        }
    )

    assert "状态：战斗日" in answer
    assert "我方：我方 星数 20 摧毁率 80.5% 进攻 18" in answer
    assert "对手：对手 星数 19 摧毁率 79.1% 进攻 17" in answer


def test_format_capital_raid_summary() -> None:
    answer = format_capital_raid_summary(
        {
            "items": [
                {
                    "state": "ended",
                    "startTime": "20260904T070000.000Z",
                    "endTime": "20260907T070000.000Z",
                    "capitalTotalLoot": 12345,
                    "raidsCompleted": 8,
                    "totalAttacks": 40,
                    "enemyDistrictsDestroyed": 28,
                    "members": [{"name": "A"}, {"name": "B"}],
                }
            ]
        }
    )

    assert "状态：已结束" in answer
    assert "都城金币：12345" in answer
    assert "参与成员：2" in answer


def test_format_player_battlelog_summary() -> None:
    answer = format_player_battlelog_summary(
        {
            "items": [
                {
                    "battleTime": "20260910T100000.000Z",
                    "opponent": {"name": "Opponent"},
                    "result": "win",
                    "stars": 3,
                    "destructionPercentage": 100,
                    "trophies": 30,
                }
            ]
        }
    )

    assert "Opponent 胜利 3/3 摧毁率 100% 奖杯 30" in answer


def test_format_player_league_history_summary() -> None:
    answer = format_player_league_history_summary({"items": [{"season": "2026-08", "trophies": 5600, "rank": 1234}]})

    assert "2026-08 奖杯 5600 排名 1234" in answer


def test_format_player_summary_item_sections() -> None:
    translations = CocTranslations(
        {
            "Battle Machine": "战争机器",
            "Rage Spell": "狂暴法术",
            "Miner": "掘地矿工",
            "Giant Gauntlet": "巨型手套",
        }
    )
    answer = format_player_summary(
        {
            "name": "Bob",
            "tag": "#ABC",
            "heroes": [{"name": "Battle Machine", "level": 30, "maxLevel": 35, "village": "BUILDER_BASE"}],
            "spells": [{"name": "Rage Spell", "level": 6, "maxLevel": 7, "village": "HOME_VILLAGE"}],
            "troops": [{"name": "Miner", "level": 9, "maxLevel": 10, "village": "HOME_VILLAGE"}],
            "heroEquipment": [{"name": "Giant Gauntlet", "level": 20, "maxLevel": 27, "village": "HOME_VILLAGE"}],
        },
        translations,
    )

    assert "- 战争机器 30/35（夜世界）" in answer
    assert "- 狂暴法术 6/7（主村）" in answer
    assert "- 掘地矿工 9/10（主村）" in answer
    assert "- 巨型手套 20/27（主村）" in answer


def test_unknown_item_name_keeps_original_text() -> None:
    answer = format_player_summary({"troops": [{"name": "Unknown Troop", "level": 1, "maxLevel": 2}]})

    assert "- Unknown Troop 1/2（-）" in answer
