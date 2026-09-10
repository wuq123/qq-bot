from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Dict, Optional
from urllib import error, parse, request

import yaml

COC_API_BASE_URL = "https://api.clashofclans.com/v1"


@dataclass(frozen=True)
class CocCommand:
    action: str
    player_tag: str


class CocService:
    def __init__(self, api_token: str, translations_path: str = "", timeout: int = 10) -> None:
        self._api_token = api_token.strip()
        self._timeout = timeout
        self._translations = CocTranslations.from_file(Path(translations_path)) if translations_path else CocTranslations({})

    def get_player_summary(self, player_tag: str) -> str:
        if not self._api_token:
            return "未配置 COC_API_TOKEN，暂时无法查询部落冲突玩家。"

        try:
            data = self._fetch_json(f"/players/{_encode_tag(normalize_player_tag(player_tag))}")
        except ValueError as exc:
            return str(exc)
        except error.HTTPError as exc:
            return _format_http_error(exc)
        except (error.URLError, TimeoutError):
            return "查询部落冲突玩家失败，请检查网络或稍后重试。"
        return format_player_summary(data, self._translations)

    def get_clan_war_summary(self, clan_tag: str) -> str:
        return self._query_tag_resource(
            clan_tag,
            "部落标签",
            lambda tag: f"/clans/{_encode_tag(tag)}/currentwar",
            format_clan_war_summary,
            "clan_war",
        )

    def get_capital_raid_summary(self, clan_tag: str) -> str:
        return self._query_tag_resource(
            clan_tag,
            "部落标签",
            lambda tag: f"/clans/{_encode_tag(tag)}/capitalraidseasons?limit=1",
            format_capital_raid_summary,
        )

    def get_player_battlelog_summary(self, player_tag: str) -> str:
        return self._query_tag_resource(
            player_tag,
            "玩家标签",
            lambda tag: f"/players/{_encode_tag(tag)}/battlelog",
            format_player_battlelog_summary,
        )

    def get_player_league_history_summary(self, player_tag: str) -> str:
        return self._query_tag_resource(
            player_tag,
            "玩家标签",
            lambda tag: f"/players/{_encode_tag(tag)}/leaguehistory",
            format_player_league_history_summary,
        )

    def get_building_time_summary(self, player_tag: str) -> str:
        try:
            normalize_player_tag(player_tag)
        except ValueError as exc:
            return str(exc)
        return "暂时无法查询建筑剩余时间：Clash of Clans 官方 API 不返回建筑列表、建筑等级或升级结束时间。"

    def _query_tag_resource(self, tag: str, tag_name: str, path_builder: Any, formatter: Any, error_context: str = "") -> str:
        if not self._api_token:
            return "未配置 COC_API_TOKEN，暂时无法查询部落冲突数据。"

        try:
            normalized_tag = normalize_tag(tag, tag_name)
            data = self._fetch_json(path_builder(normalized_tag))
        except ValueError as exc:
            return str(exc)
        except error.HTTPError as exc:
            return _format_http_error(exc, error_context)
        except (error.URLError, TimeoutError):
            return "查询部落冲突数据失败，请检查网络或稍后重试。"
        return formatter(data)

    def _fetch_json(self, path: str) -> Dict[str, Any]:
        url = f"{COC_API_BASE_URL}{path}"
        req = request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._api_token}",
            },
            method="GET",
        )
        with request.urlopen(req, timeout=self._timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def parse_coc_command(text: str) -> Optional[CocCommand]:
    value = _strip_mention(text)
    clan_war_match = re.match(r"^(查询部落战|部落战)[:：]\s*(.+)$", value)
    if clan_war_match:
        return CocCommand(action="clan_war", player_tag=clan_war_match.group(2).strip())

    capital_raid_match = re.match(r"^(查询都城突袭|都城)[:：]\s*(.+)$", value)
    if capital_raid_match:
        return CocCommand(action="capital_raid", player_tag=capital_raid_match.group(2).strip())

    battlelog_match = re.match(r"^(查询玩家战斗日志|战斗日志)[:：]\s*(.+)$", value)
    if battlelog_match:
        return CocCommand(action="battlelog", player_tag=battlelog_match.group(2).strip())

    league_history_match = re.match(r"^(查询玩家联赛历史|联赛历史)[:：]\s*(.+)$", value)
    if league_history_match:
        return CocCommand(action="league_history", player_tag=league_history_match.group(2).strip())

    building_match = re.match(r"^(查询建筑剩余时间|查看建筑剩余时间|查询玩家建筑剩余时间|查看玩家建筑剩余时间)[:：]\s*(.+)$", value)
    if building_match:
        return CocCommand(action="building_time", player_tag=building_match.group(2).strip())
    if value.startswith(("查询建筑剩余时间", "查看建筑剩余时间", "查询玩家建筑剩余时间", "查看玩家建筑剩余时间")):
        return CocCommand(action="invalid", player_tag="")

    match = re.match(r"^(查询玩家|查看玩家|部落冲突玩家|玩家)[:：]\s*(.+)$", value)
    if match:
        return CocCommand(action="player", player_tag=match.group(2).strip())
    if value.startswith(
        (
            "查询部落战",
            "部落战",
            "查询都城突袭",
            "都城",
            "查询玩家战斗日志",
            "战斗日志",
            "查询玩家联赛历史",
            "联赛历史",
            "查询玩家",
            "查看玩家",
            "部落冲突玩家",
            "玩家",
        )
    ):
        return CocCommand(action="invalid", player_tag="")
    return None


def normalize_player_tag(player_tag: str) -> str:
    return normalize_tag(player_tag, "玩家标签")


def normalize_tag(tag: str, tag_name: str) -> str:
    value = tag.strip().upper().replace(" ", "")
    if not value:
        raise ValueError(f"{tag_name}不能为空。")
    if not value.startswith("#"):
        value = f"#{value}"
    if not re.fullmatch(r"#[A-Z0-9]+", value):
        raise ValueError(f"{tag_name}格式不正确。")
    return value


def _encode_tag(tag: str) -> str:
    return parse.quote(tag, safe="")


class CocTranslations:
    def __init__(self, names: Dict[str, str]) -> None:
        self._names = names

    @classmethod
    def from_file(cls, path: Path) -> "CocTranslations":
        if not path.exists():
            return cls({})
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        names = data.get("names", {}) or {}
        return cls({str(key): str(value) for key, value in names.items()})

    def name(self, value: Any) -> str:
        text = str(value or "-")
        return self._names.get(text, text)


def format_player_summary(data: Dict[str, Any], translations: Optional[CocTranslations] = None) -> str:
    translator = translations or CocTranslations({})
    clan = data.get("clan") or {}
    clan_name = clan.get("name") or "无"
    return "\n".join(
        [
            "部落冲突玩家：",
            f"名称：{data.get('name', '-')}",
            f"标签：{data.get('tag', '-')}",
            f"经验等级：{data.get('expLevel', '-')}",
            f"大本营等级：{data.get('townHallLevel', '-')}",
            f"奖杯：{data.get('trophies', '-')}",
            f"历史最高奖杯：{data.get('bestTrophies', '-')}",
            f"战争星数：{data.get('warStars', '-')}",
            f"部落：{clan_name}",
            f"捐兵/收兵：{data.get('donations', '-')}/{data.get('donationsReceived', '-')}",
            _format_item_section("英雄", data.get("heroes"), translator),
            _format_item_section("法术", data.get("spells"), translator),
            _format_item_section("兵种", data.get("troops"), translator),
            _format_item_section("装备", data.get("heroEquipment"), translator),
        ]
    )


def format_clan_war_summary(data: Dict[str, Any]) -> str:
    state = _format_war_state(data.get("state"))
    clan = data.get("clan") or {}
    opponent = data.get("opponent") or {}
    if data.get("state") == "notInWar":
        return f"部落战：\n状态：{state}"
    return "\n".join(
        [
            "部落战：",
            f"状态：{state}",
            f"规模：{data.get('teamSize', '-')}",
            f"每人进攻次数：{data.get('attacksPerMember', '-')}",
            f"开始时间：{data.get('startTime', '-')}",
            f"结束时间：{data.get('endTime', '-')}",
            f"我方：{clan.get('name', '-')} 星数 {clan.get('stars', '-')} 摧毁率 {_percent(clan.get('destructionPercentage'))} 进攻 {clan.get('attacks', '-')}",
            f"对手：{opponent.get('name', '-')} 星数 {opponent.get('stars', '-')} 摧毁率 {_percent(opponent.get('destructionPercentage'))} 进攻 {opponent.get('attacks', '-')}",
        ]
    )


def format_capital_raid_summary(data: Dict[str, Any]) -> str:
    items = data.get("items") or []
    if not items:
        return "都城突袭：暂无赛季数据。"
    season = items[0]
    return "\n".join(
        [
            "都城突袭：",
            f"状态：{_format_raid_state(season.get('state'))}",
            f"开始时间：{season.get('startTime', '-')}",
            f"结束时间：{season.get('endTime', '-')}",
            f"都城金币：{season.get('capitalTotalLoot', '-')}",
            f"完成突袭：{season.get('raidsCompleted', '-')}",
            f"总进攻次数：{season.get('totalAttacks', '-')}",
            f"摧毁区域：{season.get('enemyDistrictsDestroyed', '-')}",
            f"参与成员：{len(season.get('members') or [])}",
        ]
    )


def format_player_battlelog_summary(data: Dict[str, Any]) -> str:
    items = data.get("items") if isinstance(data, dict) else data
    if not items:
        return "玩家战斗日志：暂无数据。"

    lines = ["玩家战斗日志："]
    for item in items[:5]:
        opponent = item.get("opponent") or item.get("defender") or {}
        lines.append(
            f"- {item.get('battleTime', '-')} {opponent.get('name', opponent.get('tag', '-'))} "
            f"{_format_result(item.get('result'))} {item.get('stars', '-')}/3 摧毁率 {_percent(item.get('destructionPercentage'))} 奖杯 {item.get('trophies', '-')}"
        )
    return "\n".join(lines)


def format_player_league_history_summary(data: Dict[str, Any]) -> str:
    items = data.get("items") if isinstance(data, dict) else data
    if not items:
        return "玩家联赛历史：暂无数据。"

    lines = ["玩家联赛历史："]
    for item in items[:5]:
        lines.append(
            f"- {item.get('season', '-')} 奖杯 {item.get('trophies', '-')} 排名 {item.get('rank', '-')}"
        )
    return "\n".join(lines)


def _format_item_section(title: str, items: Any, translations: CocTranslations) -> str:
    if not items:
        return f"{title}：无"

    lines = [f"{title}："]
    for item in items:
        if not isinstance(item, dict):
            continue
        name = translations.name(item.get("name", "-"))
        level = item.get("level", "-")
        max_level = item.get("maxLevel", "-")
        village = _format_village(item.get("village"))
        lines.append(f"- {name} {level}/{max_level}（{village}）")
    if len(lines) == 1:
        return f"{title}：无"
    return "\n".join(lines)


def _format_village(value: Any) -> str:
    if value == "HOME_VILLAGE":
        return "主村"
    if value == "BUILDER_BASE":
        return "夜世界"
    return str(value or "-")


def _format_war_state(value: Any) -> str:
    states = {
        "notInWar": "未参战",
        "preparation": "准备日",
        "inWar": "战斗日",
        "warEnded": "已结束",
    }
    return states.get(value, str(value or "-"))


def _format_raid_state(value: Any) -> str:
    states = {
        "ongoing": "进行中",
        "ended": "已结束",
    }
    return states.get(value, str(value or "-"))


def _format_result(value: Any) -> str:
    results = {
        "win": "胜利",
        "lose": "失败",
        "tie": "平局",
    }
    return results.get(value, str(value or "-"))


def _percent(value: Any) -> str:
    if value is None:
        return "-"
    return f"{value}%"


def _format_http_error(exc: error.HTTPError, error_context: str = "") -> str:
    if exc.code == 403:
        if error_context == "clan_war":
            return "部落战 API 拒绝访问：请检查 COC_API_TOKEN 和服务器 IP 白名单；如果其他部落冲突查询正常，通常是该部落在游戏内关闭了公开战争日志。"
        return "部落冲突 API 拒绝访问，请检查 COC_API_TOKEN 或服务器 IP 白名单。"
    if exc.code == 404:
        return "未找到该部落冲突玩家，请检查玩家标签。"
    if exc.code == 429:
        return "部落冲突 API 请求过于频繁，请稍后再试。"
    if exc.code == 503:
        return "部落冲突 API 正在维护，请稍后再试。"
    return f"查询部落冲突玩家失败，API 返回状态码 {exc.code}。"


def _strip_mention(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"<@!?\d+>", "", value)
    return value.strip()
