import base64
from dataclasses import dataclass
import json
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional
from urllib import error, parse, request
from uuid import uuid4

import yaml
from Crypto.Cipher import AES

from qqbot_app.bot_message import BotAnswer, BotMessage
from qqbot_app.wuwa_renderer import render_character_card, render_text_card

WUWA_CN_SERVER_ID = "76402e5b20be2c39f095a152090afddc"
KURO_API_BASE_URL = "https://api.kurobbs.com"
WUWA_GACHA_CN_URL = "https://gmserver-api.aki-game2.com/gacha/record/query"
WUWA_GACHA_NET_URL = "https://gmserver-api.aki-game2.net/gacha/record/query"
GACHA_POOL_NAMES = {
    "1": "角色活动",
    "2": "武器活动",
    "3": "角色常驻",
    "4": "武器常驻",
    "5": "新手唤取",
    "6": "新手自选",
    "7": "感恩定向",
}
SMS_LOGIN_TTL_SECONDS = 600


@dataclass(frozen=True)
class WuwaCommand:
    action: str
    value: str = ""
    server_id: str = ""


class WuwaService:
    def __init__(self, data_dir: str, timeout: int = 10) -> None:
        self._data_dir = Path(data_dir)
        self._timeout = timeout
        self._pending_logins: Dict[str, Dict[str, Any]] = {}

    def request_sms_code(self, user_id: str, mobile: str) -> str:
        mobile = mobile.strip()
        if not re.fullmatch(r"1\d{10}", mobile):
            return "手机号格式不正确，请输入 11 位中国大陆手机号。"

        dev_code = uuid4().hex.upper()
        distinct_id = str(uuid4())
        try:
            data = self._post_json_url(
                f"{KURO_API_BASE_URL}/user/getSmsCode",
                {"mobile": mobile, "geeTestData": ""},
                _login_headers(dev_code, distinct_id),
            )
        except WuwaApiError as exc:
            return str(exc)

        payload = data.get("data") or {}
        self._pending_logins[user_id] = {
            "mobile": mobile,
            "dev_code": dev_code,
            "distinct_id": distinct_id,
            "expires_at": time.monotonic() + SMS_LOGIN_TTL_SECONDS,
        }
        if payload.get("geeTest"):
            return (
                "库街区要求完成人机验证，本次短信未发送。请在 10 分钟内打开库街区 App 登录页，"
                "或访问 https://wiki.kurobbs.com/pns/home 点击右上角头像，输入同一手机号并完成验证以获取短信；"
                "收到后回到此私聊发送：鸣潮验证码：123456。无需在库街区完成登录。"
            )
        return f"验证码已发送至 {_mask_mobile(mobile)}，请在 10 分钟内私聊发送：鸣潮验证码：123456。继续登录可能使库街区 App 当前登录失效。"

    def submit_sms_code(self, user_id: str, code: str) -> str:
        code = code.strip()
        if not re.fullmatch(r"\d{4,8}", code):
            return "验证码格式不正确，请输入 4 至 8 位数字。"

        pending = self._pending_logins.get(user_id)
        if not pending:
            return "未发送验证码，请先私聊发送：鸣潮登录：<手机号>。"
        if time.monotonic() > pending["expires_at"]:
            self._pending_logins.pop(user_id, None)
            return "鸣潮登录请求已过期，请重新发送：鸣潮登录：<手机号>。"

        headers = _login_headers(pending["dev_code"], pending["distinct_id"])
        try:
            data = self._post_json_url(
                f"{KURO_API_BASE_URL}/user/sdkLogin",
                {
                    "code": code,
                    "devCode": pending["dev_code"],
                    "gameList": "",
                    "mobile": pending["mobile"],
                },
                headers,
            )
        except WuwaApiError as exc:
            return str(exc)

        payload = data.get("data") or {}
        token = str(payload.get("token") or "").strip()
        if not token:
            return "库街区登录成功，但响应中没有 Token，请稍后重试。"

        self._pending_logins.pop(user_id, None)
        binding = {"token": token}
        self._save_binding(user_id, binding)
        try:
            roles = self._fetch_bound_roles(token, pending["dev_code"], pending["distinct_id"])
        except WuwaApiError as exc:
            return f"库街区登录成功，Token 已保存，但自动读取角色失败：{exc}"

        role = next((item for item in roles if item.get("isDefault")), None)
        if role is None and len(roles) == 1:
            role = roles[0]
        if role is not None:
            role_id = str(role.get("roleId") or "").strip()
            server_id = str(role.get("serverId") or WUWA_CN_SERVER_ID).strip()
            if role_id:
                binding["role_id"] = role_id
                binding["server_id"] = server_id
                self._save_binding(user_id, binding)
                role_name = str(role.get("roleName") or "-")
                return f"库街区登录成功，已自动绑定鸣潮角色：{role_name}（{role_id}）。"

        if not roles:
            return "库街区登录成功，Token 已保存，但账号下没有找到已绑定的鸣潮角色。"
        return _format_role_choices(roles)

    def bind_token(self, user_id: str, token: str) -> str:
        token = token.strip()
        if not token:
            return "鸣潮 Token 不能为空。"
        binding = self._load_binding(user_id)
        binding["token"] = token
        self._save_binding(user_id, binding)
        return "已绑定鸣潮 Token。"

    def bind_role(self, user_id: str, role_id: str, server_id: str = "") -> str:
        role_id = role_id.strip()
        server_id = (server_id or WUWA_CN_SERVER_ID).strip()
        if not role_id:
            return "鸣潮角色 ID 不能为空。"
        if not re.fullmatch(r"\d+", role_id):
            return "鸣潮角色 ID 格式不正确。"
        binding = self._load_binding(user_id)
        binding["role_id"] = role_id
        binding["server_id"] = server_id
        self._save_binding(user_id, binding)
        return f"已绑定鸣潮角色：{role_id}。"

    def describe_binding(self, user_id: str) -> str:
        binding = self._load_binding(user_id)
        token_status = "已绑定" if binding.get("token") else "未绑定"
        role_id = binding.get("role_id") or "未绑定"
        server_id = binding.get("server_id") or WUWA_CN_SERVER_ID
        return "\n".join(["鸣潮绑定：", f"Token：{token_status}", f"角色ID：{role_id}", f"区服：{server_id}"])

    def delete_binding(self, user_id: str) -> str:
        self._pending_logins.pop(user_id, None)
        user_dir = self._user_dir(user_id)
        binding_path = user_dir / "binding.yaml"
        if binding_path.exists():
            binding_path.unlink()
        return "已删除鸣潮绑定。"

    def get_profile_summary(self, user_id: str) -> BotAnswer:
        binding_error = self._binding_error(user_id, need_role=True)
        if binding_error:
            return binding_error
        try:
            data = self._fetch_widget_data(self._load_binding(user_id))
        except WuwaApiError as exc:
            return str(exc)
        summary = format_profile_summary(data)
        return _text_card_message("鸣潮面板", summary)

    def get_stamina_summary(self, user_id: str) -> BotAnswer:
        binding_error = self._binding_error(user_id, need_role=True)
        if binding_error:
            return binding_error
        try:
            data = self._fetch_widget_data(self._load_binding(user_id))
        except WuwaApiError as exc:
            return str(exc)
        summary = format_stamina_summary(data)
        return _text_card_message("鸣潮体力", summary)

    def get_character_summary(self, user_id: str, character_name: str) -> BotAnswer:
        binding_error = self._binding_error(user_id, need_role=True)
        if binding_error:
            return binding_error
        binding = self._load_binding(user_id)
        try:
            role_headers = self._prepare_character_access(binding)
            data = self._fetch_character_list(binding, role_headers)
        except WuwaApiError as exc:
            return str(exc)
        if not character_name:
            return format_character_list(data)
        character = _find_character(data, character_name)
        if not character:
            return f"未找到角色：{character_name}。"
        character_id = _character_id(character)
        if not character_id:
            return f"角色数据缺少角色 ID：{character_name}。"
        try:
            detail = _payload(self._fetch_character_detail(binding, character_id, role_headers))
        except WuwaApiError as exc:
            return str(exc)
        detail.setdefault("roleName", _character_name(character))
        summary = format_character_summary(detail)
        return _character_card_message(summary, detail)

    def import_gacha_url(self, user_id: str, url: str) -> str:
        params = _parse_gacha_url(url)
        if not params:
            return "鸣潮抽卡链接格式不正确。请粘贴游戏内唤取记录页面 URL。"
        try:
            records = self._fetch_gacha_records(params)
        except WuwaApiError as exc:
            return str(exc)
        return self._merge_gacha_records(user_id, records)

    def import_gacha_json(self, user_id: str, raw_json: str) -> str:
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            return "鸣潮抽卡 JSON 格式不正确。"
        records = _extract_gacha_records(data)
        if not records:
            return "没有从 JSON 中读取到鸣潮抽卡记录。"
        return self._merge_gacha_records(user_id, records)

    def get_gacha_analysis(self, user_id: str, pool_name: str = "") -> BotAnswer:
        records = self._load_gacha_records(user_id)
        if not records:
            return "暂无鸣潮抽卡记录。请先发送：导入鸣潮抽卡：<唤取记录URL>。"
        summary = format_gacha_analysis(records, pool_name)
        return _text_card_message("鸣潮抽卡分析", summary)

    def _binding_error(self, user_id: str, need_role: bool) -> str:
        binding = self._load_binding(user_id)
        if not binding.get("token"):
            return "未绑定鸣潮 Token。请先发送：绑定鸣潮Token：<库街区token>。"
        if need_role and not binding.get("role_id"):
            return "未绑定鸣潮角色。请先发送：绑定鸣潮角色：<role_id>。"
        return ""

    def _fetch_widget_data(self, binding: Dict[str, Any]) -> Dict[str, Any]:
        body = {
            "gameId": "3",
            "roleId": str(binding.get("role_id", "")),
            "serverId": str(binding.get("server_id") or WUWA_CN_SERVER_ID),
            "type": "2",
            "sizeType": "1",
        }
        return self._post_kuro_json("/gamer/widget/game3/getData", binding["token"], body)

    def _prepare_character_access(self, binding: Dict[str, Any]) -> Dict[str, str]:
        did = str(uuid4())
        roles = self._fetch_bound_roles(binding["token"], uuid4().hex.upper(), did)
        role_id = str(binding.get("role_id", ""))
        server_id = str(binding.get("server_id") or WUWA_CN_SERVER_ID)
        bound_role = next(
            (
                role
                for role in roles
                if str(role.get("roleId", "")) == role_id and str(role.get("serverId", "")) == server_id
            ),
            None,
        )
        if not bound_role:
            raise WuwaApiError("库街区中未找到当前绑定角色，请重新登录或绑定角色。")
        user_id = str(bound_role.get("userId") or "")
        if not user_id:
            raise WuwaApiError("库街区角色缺少用户 ID，请重新登录后再试。")

        token_headers = _role_headers(did)
        token_headers["Token"] = binding["token"]
        token_data = self._post_json_url(
            f"{KURO_API_BASE_URL}/aki/roleBox/requestToken",
            {"roleId": role_id, "serverId": server_id, "userId": user_id},
            token_headers,
        )
        access_token = _access_token(token_data)
        if not access_token:
            raise WuwaApiError("获取鸣潮角色访问凭证失败，请重新登录后再试。")

        role_headers = _role_headers(did)
        role_headers["b-at"] = access_token
        self._post_json_url(
            f"{KURO_API_BASE_URL}/aki/roleBox/akiBox/refreshData",
            {"gameId": "3", "roleId": role_id, "serverId": server_id},
            role_headers,
        )
        return role_headers

    def _fetch_character_list(self, binding: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        body = {
            "gameId": "3",
            "roleId": str(binding.get("role_id", "")),
            "serverId": str(binding.get("server_id") or WUWA_CN_SERVER_ID),
        }
        data = self._post_json_url(f"{KURO_API_BASE_URL}/aki/roleBox/akiBox/roleData", body, headers)
        return _decrypt_kuro_response(data)

    def _fetch_character_detail(
        self,
        binding: Dict[str, Any],
        character_id: str,
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        body = {
            "gameId": "3",
            "roleId": str(binding.get("role_id", "")),
            "serverId": str(binding.get("server_id") or WUWA_CN_SERVER_ID),
            "id": character_id,
        }
        data = self._post_json_url(f"{KURO_API_BASE_URL}/aki/roleBox/akiBox/getRoleDetail", body, headers)
        return _decrypt_kuro_response(data)

    def _fetch_bound_roles(self, token: str, dev_code: str, distinct_id: str) -> List[Dict[str, Any]]:
        headers = _login_headers(dev_code, distinct_id)
        headers["Token"] = token
        data = self._post_json_url(f"{KURO_API_BASE_URL}/user/role/findRoleList", {"gameId": "3"}, headers)
        roles = data.get("data") or []
        return [item for item in roles if isinstance(item, dict)]

    def _fetch_gacha_records(self, params: Dict[str, str]) -> List[Dict[str, Any]]:
        endpoint = WUWA_GACHA_NET_URL if "oversea" in params.get("_source", "") or params.get("svr_area") != "cn" else WUWA_GACHA_CN_URL
        pool_types = list(GACHA_POOL_NAMES)
        records: List[Dict[str, Any]] = []
        for pool_type in pool_types:
            page = 1
            while True:
                body = {
                    "playerId": params["player_id"],
                    "serverId": params["svr_id"],
                    "cardPoolId": params["resources_id"],
                    "cardPoolType": pool_type,
                    "recordId": params["record_id"],
                    "languageCode": params.get("lang", "zh-Hans"),
                    "page": str(page),
                    "size": "100",
                }
                response_data = self._post_json_url(endpoint, body)
                page_records = _extract_gacha_records(response_data)
                if not page_records:
                    break
                records.extend(page_records)
                if len(page_records) < 100:
                    break
                page += 1
                if page > 20:
                    break
        if not records:
            raise WuwaApiError("没有读取到鸣潮抽卡记录；链接可能已过期。")
        return records

    def _post_kuro_json(self, path: str, token: str, body: Dict[str, str]) -> Dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "Source": "android",
            "Token": token,
            "User-Agent": "KuroGameBox/2.2.0",
            "Origin": "https://web-static.kurobbs.com",
        }
        return self._post_json_url(f"{KURO_API_BASE_URL}{path}", body, headers)

    def _post_json_url(self, url: str, body: Dict[str, str], headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        payload = parse.urlencode(body).encode("utf-8")
        req = request.Request(url, data=payload, headers=headers or {"Accept": "application/json"}, method="POST")
        try:
            with request.urlopen(req, timeout=self._timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            raise WuwaApiError(_format_http_error(exc.code)) from exc
        except (error.URLError, TimeoutError) as exc:
            raise WuwaApiError("查询鸣潮数据失败，请检查网络或稍后重试。") from exc
        except json.JSONDecodeError as exc:
            raise WuwaApiError("鸣潮接口返回格式不正确。") from exc

        code = data.get("code")
        if code not in (None, 0, 200):
            raise WuwaApiError(_format_api_code(code, data.get("msg")))
        return data

    def _merge_gacha_records(self, user_id: str, records: List[Dict[str, Any]]) -> str:
        old_records = self._load_gacha_records(user_id)
        merged = {gacha_record_key(record): record for record in old_records}
        before = len(merged)
        for record in records:
            merged[gacha_record_key(record)] = record
        new_records = list(merged.values())
        new_records.sort(key=_gacha_sort_key, reverse=True)
        gacha_path = self._user_dir(user_id) / "gacha.json"
        gacha_path.write_text(json.dumps(new_records, ensure_ascii=False, indent=2), encoding="utf-8")
        return f"已导入鸣潮抽卡记录 {len(new_records) - before} 条，当前共 {len(new_records)} 条。"

    def _load_gacha_records(self, user_id: str) -> List[Dict[str, Any]]:
        path = self._user_dir(user_id) / "gacha.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    def _load_binding(self, user_id: str) -> Dict[str, Any]:
        path = self._user_dir(user_id) / "binding.yaml"
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}

    def _save_binding(self, user_id: str, binding: Dict[str, Any]) -> None:
        path = self._user_dir(user_id) / "binding.yaml"
        path.write_text(yaml.safe_dump(binding, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def _user_dir(self, user_id: str) -> Path:
        user_dir = self._data_dir / _safe_user_id(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir


class WuwaApiError(Exception):
    pass


def parse_wuwa_command(text: str) -> Optional[WuwaCommand]:
    value = _strip_mention(text)
    login_match = re.match(r"^鸣潮登录[:：]\s*(.+)$", value)
    if login_match:
        return WuwaCommand("request_sms", login_match.group(1).strip())

    code_match = re.match(r"^鸣潮验证码[:：]\s*(.+)$", value)
    if code_match:
        return WuwaCommand("submit_sms", code_match.group(1).strip())

    token_match = re.match(r"^绑定鸣潮Token[:：]\s*(.+)$", value, re.IGNORECASE | re.S)
    if token_match:
        return WuwaCommand("bind_token", token_match.group(1).strip())

    role_match = re.match(r"^绑定鸣潮角色[:：]\s*(\d+)(?:\s+区服[:：]\s*(\S+))?\s*$", value)
    if role_match:
        return WuwaCommand("bind_role", role_match.group(1), role_match.group(2) or WUWA_CN_SERVER_ID)

    if value == "查看鸣潮绑定":
        return WuwaCommand("describe_binding")
    if value == "删除鸣潮绑定":
        return WuwaCommand("delete_binding")
    if value == "鸣潮面板":
        return WuwaCommand("profile")
    if value == "鸣潮体力":
        return WuwaCommand("stamina")
    if value in {"练度", "鸣潮练度"}:
        return WuwaCommand("character")

    character_match = re.match(r"^(练度|鸣潮练度)[:：]\s*(.+)$", value)
    if character_match:
        return WuwaCommand("character", character_match.group(2).strip())

    import_json_match = re.match(r"^导入鸣潮抽卡JSON[:：]\s*(.+)$", value, re.IGNORECASE | re.S)
    if import_json_match:
        return WuwaCommand("import_gacha_json", import_json_match.group(1).strip())

    import_match = re.match(r"^导入鸣潮抽卡[:：]\s*(.+)$", value, re.S)
    if import_match:
        return WuwaCommand("import_gacha_url", import_match.group(1).strip())

    gacha_match = re.match(r"^(鸣潮抽卡|抽卡分析)(?:[:：]\s*(.+))?$", value)
    if gacha_match:
        return WuwaCommand("gacha_analysis", (gacha_match.group(2) or "").strip())

    if value.startswith(("鸣潮登录", "鸣潮验证码", "绑定鸣潮", "鸣潮面板", "鸣潮体力", "练度", "鸣潮练度", "导入鸣潮抽卡", "鸣潮抽卡", "抽卡分析")):
        return WuwaCommand("invalid")
    return None


def format_profile_summary(data: Dict[str, Any]) -> str:
    payload = _payload(data)
    return "\n".join(
        [
            "鸣潮面板：",
            f"昵称：{payload.get('roleName', '-')}",
            f"角色ID：{payload.get('roleId', '-')}",
            f"区服：{payload.get('serverName', '-')}",
            f"结晶波片：{_counter(payload.get('energyData'))}",
            f"活跃度：{_counter(payload.get('livenessData'))}",
            f"结晶单质：{_counter(payload.get('storeEnergyData'))}",
            f"逆境深塔：{_counter(payload.get('towerData'))}",
        ]
    )


def format_stamina_summary(data: Dict[str, Any]) -> str:
    payload = _payload(data)
    energy = payload.get("energyData") or {}
    lines = [
        "鸣潮体力：",
        f"结晶波片：{_counter(energy)}",
        f"结晶单质：{_counter(payload.get('storeEnergyData'))}",
        f"活跃度：{_counter(payload.get('livenessData'))}",
    ]
    if energy.get("refreshTimeStamp"):
        lines.append(f"波片回满时间戳：{energy.get('refreshTimeStamp')}")
    return "\n".join(lines)


def _text_card_message(title: str, summary: str) -> BotAnswer:
    try:
        return BotMessage(content=summary, image=render_text_card(title, summary))
    except Exception:
        return summary


def _character_card_message(summary: str, data: Dict[str, Any]) -> BotAnswer:
    try:
        return BotMessage(content=summary, image=render_character_card(data))
    except Exception:
        return summary


def format_character_list(data: Dict[str, Any]) -> str:
    characters = _characters(data)
    if not characters:
        return "暂无鸣潮角色数据。"
    names = [_character_name(item) for item in characters[:20]]
    return "鸣潮角色列表：\n" + "\n".join(f"- {name}" for name in names if name)


def format_character_summary(character: Dict[str, Any]) -> str:
    role = character.get("role") or character
    weapon_data = character.get("weaponData") or character.get("weapon") or {}
    weapon = weapon_data.get("weapon") or weapon_data
    skill_text = _format_skills(character.get("skillList") or character.get("skills"))
    return "\n".join(
        [
            f"鸣潮练度：{_character_name(character)}",
            f"等级：{_value(character, 'level', 'roleLevel')}",
            f"突破/阶级：{_value(role, 'breach', 'breakLevel', 'promoteLevel')}",
            f"共鸣链：{_chain_level(character)}",
            f"武器：{_value(weapon, 'name', 'weaponName')} {_value(weapon_data, 'level', 'weaponLevel')}",
            f"技能：{skill_text}",
            f"声骸：{len(_echoes(character))} 个",
        ]
    )


def format_gacha_analysis(records: List[Dict[str, Any]], pool_name: str = "") -> str:
    filtered = _filter_records_by_pool(records, pool_name)
    if not filtered:
        return f"没有找到“{pool_name}”对应的鸣潮抽卡记录。"

    sorted_records = sorted(filtered, key=_gacha_sort_key, reverse=True)
    five_star = [record for record in sorted_records if _rarity(record) >= 5]
    four_star = [record for record in sorted_records if _rarity(record) == 4]
    pity = _current_pity(sorted_records)
    lines = [
        "鸣潮抽卡分析：",
        f"卡池：{pool_name or '全部'}",
        f"总抽数：{len(sorted_records)}",
        f"五星：{len(five_star)}",
        f"四星：{len(four_star)}",
        f"当前垫数：{pity}",
    ]
    if five_star:
        average = round(len(sorted_records) / len(five_star), 1)
        lines.append(f"平均五星抽数：{average}")
        lines.append("最近五星：")
        for record in five_star[:5]:
            lines.append(f"- {_record_time(record)} {_record_name(record)}")
    lines.append("卡池统计：")
    for pool, count in _pool_counts(sorted_records).items():
        lines.append(f"- {pool}: {count}")
    return "\n".join(lines)


def gacha_record_key(record: Dict[str, Any]) -> str:
    return "|".join(
        [
            str(record.get("id") or record.get("recordId") or ""),
            str(record.get("cardPoolType") or record.get("poolType") or record.get("pool") or ""),
            str(record.get("resourceId") or record.get("itemId") or record.get("name") or ""),
            str(record.get("time") or record.get("gachaTs") or record.get("drawTime") or ""),
            str(record.get("pos") or ""),
        ]
    )


def _parse_gacha_url(url: str) -> Dict[str, str]:
    parsed = parse.urlparse(url.strip())
    query = parsed.query
    if parsed.fragment and "?" in parsed.fragment:
        query = parsed.fragment.split("?", 1)[1]
    params = {key: values[-1] for key, values in parse.parse_qs(query).items()}
    required = {"player_id", "svr_id", "record_id", "resources_id"}
    if not required.issubset(params):
        return {}
    params["_source"] = parsed.netloc
    return params


def _extract_gacha_records(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("data", "records", "list", "items"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _extract_gacha_records(value)
            if nested:
                return nested
    return []


def _format_http_error(code: int) -> str:
    if code in {401, 403}:
        return "鸣潮接口拒绝访问，请检查 Token 是否有效。"
    if code == 429:
        return "鸣潮接口请求过于频繁，请稍后再试。"
    if code >= 500:
        return "鸣潮接口暂时不可用，请稍后再试。"
    return f"查询鸣潮数据失败，接口返回状态码 {code}。"


def _format_api_code(code: Any, msg: Any) -> str:
    if code == 242:
        return "鸣潮验证码发送过于频繁，请稍后再试。"
    if code == -130:
        return "鸣潮验证码错误或已过期，请检查后重试。"
    if code == -10000:
        return "鸣潮登录参数不完整，请重新发起登录。"
    if code == 220:
        return "鸣潮 Token 已失效，请重新绑定。"
    if code == 6001:
        return "暂无鸣潮角色数据，请确认库街区已绑定该角色。"
    return f"查询鸣潮数据失败：{msg or code}。"


def _safe_user_id(user_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", user_id or "unknown")


def _login_headers(dev_code: str, distinct_id: str) -> Dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "osVersion": "Android",
        "devCode": dev_code,
        "distinct_id": distinct_id,
        "countryCode": "CN",
        "source": "android",
        "lang": "zh-Hans",
        "version": "2.2.0",
        "versionCode": "2200",
        "channelId": "2",
        "User-Agent": "okhttp/3.11.0",
    }


def _role_headers(did: str) -> Dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        "source": "android",
        "osVersion": "35",
        "countryCode": "CN",
        "model": "2201122C",
        "lang": "zh-Hans",
        "version": "2.5.1",
        "versionCode": "2510",
        "x-requested-with": "com.kurogame.kjq",
        "User-Agent": "okhttp/3.11.0",
        "did": did,
    }


def _access_token(data: Dict[str, Any]) -> str:
    payload = data.get("data")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("accessToken") or "")


def _decrypt_kuro_response(data: Dict[str, Any]) -> Dict[str, Any]:
    payload = data.get("data")
    if not isinstance(payload, str):
        return data
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        try:
            encrypted = base64.b64decode(payload, validate=True)
            key = base64.b64decode("XSNLFgNCth8j8oJI3cNIdw==")
            decrypted = AES.new(key, AES.MODE_ECB).decrypt(encrypted)
            padding = decrypted[-1]
            if padding < 1 or padding > AES.block_size or decrypted[-padding:] != bytes([padding]) * padding:
                raise ValueError("invalid padding")
            decoded = json.loads(decrypted[:-padding].decode("utf-8"))
        except (ValueError, IndexError, json.JSONDecodeError) as exc:
            raise WuwaApiError("鸣潮角色数据解密失败，请稍后重试。") from exc
    if not isinstance(decoded, dict):
        raise WuwaApiError("鸣潮角色数据格式不正确。")
    result = dict(data)
    result["data"] = decoded
    return result


def _mask_mobile(mobile: str) -> str:
    return f"{mobile[:3]}****{mobile[-4:]}"


def _format_role_choices(roles: List[Dict[str, Any]]) -> str:
    lines = ["库街区登录成功，检测到多个鸣潮角色，请选择一个："]
    for role in roles:
        role_id = str(role.get("roleId") or "-")
        role_name = str(role.get("roleName") or "-")
        server_id = str(role.get("serverId") or WUWA_CN_SERVER_ID)
        server_name = str(role.get("serverName") or "-")
        lines.append(f"- {role_name}（{role_id}，{server_name}）")
        lines.append(f"  发送：绑定鸣潮角色：{role_id} 区服：{server_id}")
    return "\n".join(lines)


def _strip_mention(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"<@!?\d+>", "", value)
    return value.strip()


def _payload(data: Dict[str, Any]) -> Dict[str, Any]:
    payload = data.get("data") if isinstance(data, dict) else {}
    return payload if isinstance(payload, dict) else data


def _counter(value: Any) -> str:
    if not isinstance(value, dict):
        return "-"
    cur = value.get("cur", value.get("value", "-"))
    total = value.get("total", "-")
    return f"{cur}/{total}" if total != "-" else str(cur)


def _characters(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    payload = _payload(data)
    for key in ("roleList", "roles", "characters", "avatarList"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _find_character(data: Dict[str, Any], character_name: str) -> Optional[Dict[str, Any]]:
    target = character_name.strip()
    for character in _characters(data):
        if _character_name(character) == target:
            return character
    return None


def _character_name(character: Dict[str, Any]) -> str:
    role = character.get("role") if isinstance(character.get("role"), dict) else character
    return str(_value(role, "name", "roleName", "characterName"))


def _character_id(character: Dict[str, Any]) -> str:
    for key in ("roleId", "id", "characterId"):
        value = character.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _value(data: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return "-"


def _format_skills(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "-"
    parts = []
    for skill in value[:6]:
        if isinstance(skill, dict):
            skill_data = skill.get("skill") if isinstance(skill.get("skill"), dict) else skill
            parts.append(f"{_value(skill_data, 'name', 'skillName')} {_value(skill, 'level', 'skillLevel')}")
    return "、".join(parts) if parts else "-"


def _echoes(character: Dict[str, Any]) -> List[Dict[str, Any]]:
    phantom_data = character.get("phantomData")
    if isinstance(phantom_data, dict):
        value = phantom_data.get("equipPhantomList")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    for key in ("phantomList", "echoList", "echoes", "equipPhantomList"):
        value = character.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _chain_level(character: Dict[str, Any]) -> Any:
    chains = character.get("chainList")
    if isinstance(chains, list):
        return sum(1 for item in chains if isinstance(item, dict) and item.get("unlocked"))
    role = character.get("role") if isinstance(character.get("role"), dict) else character
    return _value(role, "chainUnlockNum", "chain", "chainLevel", "resonanceChain")


def _filter_records_by_pool(records: List[Dict[str, Any]], pool_name: str) -> List[Dict[str, Any]]:
    if not pool_name:
        return records
    return [record for record in records if pool_name in _pool_name(record)]


def _pool_name(record: Dict[str, Any]) -> str:
    value = str(record.get("cardPoolType") or record.get("poolType") or record.get("pool") or "")
    return GACHA_POOL_NAMES.get(value, value or "未知")


def _pool_counts(records: List[Dict[str, Any]]) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for record in records:
        pool = _pool_name(record)
        result[pool] = result.get(pool, 0) + 1
    return result


def _current_pity(records: List[Dict[str, Any]]) -> int:
    count = 0
    for record in records:
        if _rarity(record) >= 5:
            break
        count += 1
    return count


def _rarity(record: Dict[str, Any]) -> int:
    value = record.get("qualityLevel", record.get("rank", record.get("rarity", 0)))
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _record_name(record: Dict[str, Any]) -> str:
    return str(record.get("name") or record.get("resourceName") or record.get("itemName") or "-")


def _record_time(record: Dict[str, Any]) -> str:
    return str(record.get("time") or record.get("gachaTs") or record.get("drawTime") or "-")


def _gacha_sort_key(record: Dict[str, Any]) -> str:
    return f"{_record_time(record)}|{record.get('pos', '')}"
