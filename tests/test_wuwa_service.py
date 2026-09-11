import base64
import json
from pathlib import Path
from urllib import error, parse

import pytest
from Crypto.Cipher import AES

from qqbot_app.providers import BotMessage
from qqbot_app.wuwa_service import (
    WUWA_CN_SERVER_ID,
    WuwaService,
    format_character_summary,
    format_gacha_analysis,
    format_profile_summary,
    parse_wuwa_command,
)


class _Response:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _encrypt_kuro_data(data: object) -> str:
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    padding = 16 - len(raw) % 16
    padded = raw + bytes([padding]) * padding
    key = base64.b64decode("XSNLFgNCth8j8oJI3cNIdw==")
    encrypted = AES.new(key, AES.MODE_ECB).encrypt(padded)
    return base64.b64encode(encrypted).decode("ascii")


def test_bind_token_and_role(tmp_path: Path) -> None:
    service = WuwaService(str(tmp_path))

    token_answer = service.bind_token("u1", "token-1")
    role_answer = service.bind_role("u1", "101234567")
    binding = service.describe_binding("u1")

    assert token_answer == "已绑定鸣潮 Token。"
    assert role_answer == "已绑定鸣潮角色：101234567。"
    assert "Token：已绑定" in binding
    assert "角色ID：101234567" in binding
    assert "token-1" not in binding


def test_sms_login_binds_default_role(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = WuwaService(str(tmp_path))
    responses = [
        '{"code":200,"data":{"geeTest":false}}',
        '{"code":200,"data":{"token":"token-1","refreshToken":"refresh-1"}}',
        '{"code":200,"data":['
        '{"roleId":"101234567","roleName":"漂泊者","serverId":"server-1","serverName":"鸣潮","isDefault":true}'
        ']}',
    ]

    def fake_urlopen(req: object, timeout: int = 10) -> _Response:
        return _Response(responses.pop(0))

    monkeypatch.setattr("qqbot_app.wuwa_service.request.urlopen", fake_urlopen)

    request_answer = service.request_sms_code("u1", "13800138000")
    login_answer = service.submit_sms_code("u1", "123456")
    binding = service.describe_binding("u1")

    assert "138****8000" in request_answer
    assert "登录成功" in login_answer
    assert "101234567" in login_answer
    assert "Token：已绑定" in binding
    assert "角色ID：101234567" in binding
    assert "区服：server-1" in binding
    saved_binding = (tmp_path / "u1" / "binding.yaml").read_text(encoding="utf-8")
    assert "13800138000" not in saved_binding
    assert "mobile:" not in saved_binding
    assert "code:" not in saved_binding
    assert "refresh-1" not in saved_binding


def test_sms_login_lists_multiple_roles_without_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = WuwaService(str(tmp_path))
    responses = [
        '{"code":200,"data":{"geeTest":false}}',
        '{"code":200,"data":{"token":"token-1"}}',
        '{"code":200,"data":['
        '{"roleId":"101","roleName":"角色一","serverId":"s1","serverName":"一区"},'
        '{"roleId":"102","roleName":"角色二","serverId":"s2","serverName":"二区"}'
        ']}',
    ]

    monkeypatch.setattr(
        "qqbot_app.wuwa_service.request.urlopen",
        lambda req, timeout=10: _Response(responses.pop(0)),
    )

    service.request_sms_code("u1", "13800138000")
    answer = service.submit_sms_code("u1", "123456")

    assert "检测到多个鸣潮角色" in answer
    assert "角色一（101，一区）" in answer
    assert "绑定鸣潮角色：101 区服：s1" in answer
    assert "角色ID：未绑定" in service.describe_binding("u1")


def test_sms_login_requires_captcha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = WuwaService(str(tmp_path))
    responses = [
        '{"code":200,"data":{"geeTest":true}}',
        '{"code":200,"data":{"token":"token-1"}}',
        '{"code":200,"data":[]}',
    ]
    monkeypatch.setattr(
        "qqbot_app.wuwa_service.request.urlopen",
        lambda req, timeout=10: _Response(responses.pop(0)),
    )

    request_answer = service.request_sms_code("u1", "13800138000")
    login_answer = service.submit_sms_code("u1", "123456")

    assert "人机验证" in request_answer
    assert "本次短信未发送" in request_answer
    assert "wiki.kurobbs.com" in request_answer
    assert "鸣潮验证码：123456" in request_answer
    assert "登录成功" in login_answer
    assert "Token：已绑定" in service.describe_binding("u1")


def test_sms_login_pending_request_expires(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = WuwaService(str(tmp_path))
    now = 100.0
    monkeypatch.setattr("qqbot_app.wuwa_service.time.monotonic", lambda: now)
    monkeypatch.setattr(
        "qqbot_app.wuwa_service.request.urlopen",
        lambda req, timeout=10: _Response('{"code":200,"data":{"geeTest":false}}'),
    )
    service.request_sms_code("u1", "13800138000")

    now = 701.0
    answer = service.submit_sms_code("u1", "123456")

    assert "已过期" in answer


def test_sms_login_validates_mobile_and_code(tmp_path: Path) -> None:
    service = WuwaService(str(tmp_path))

    assert service.request_sms_code("u1", "123") == "手机号格式不正确，请输入 11 位中国大陆手机号。"
    assert service.submit_sms_code("u1", "abc") == "验证码格式不正确，请输入 4 至 8 位数字。"


def test_sms_login_reports_wrong_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = WuwaService(str(tmp_path))
    responses = [
        '{"code":200,"data":{"geeTest":false}}',
        '{"code":-130,"msg":"code error"}',
    ]
    monkeypatch.setattr(
        "qqbot_app.wuwa_service.request.urlopen",
        lambda req, timeout=10: _Response(responses.pop(0)),
    )

    service.request_sms_code("u1", "13800138000")
    answer = service.submit_sms_code("u1", "123456")

    assert answer == "鸣潮验证码错误或已过期，请检查后重试。"


def test_delete_binding(tmp_path: Path) -> None:
    service = WuwaService(str(tmp_path))
    service.bind_token("u1", "token-1")

    answer = service.delete_binding("u1")

    assert answer == "已删除鸣潮绑定。"
    assert "Token：未绑定" in service.describe_binding("u1")


def test_profile_requires_binding(tmp_path: Path) -> None:
    service = WuwaService(str(tmp_path))

    assert "未绑定鸣潮 Token" in service.get_profile_summary("u1")


def test_fetch_profile_formats_widget_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = WuwaService(str(tmp_path))
    service.bind_token("u1", "token-1")
    service.bind_role("u1", "101234567")

    def fake_urlopen(req: object, timeout: int = 10) -> _Response:
        return _Response(
            '{"code":200,"data":{"roleName":"漂泊者","roleId":"101234567","serverName":"鸣潮",'
            '"energyData":{"cur":120,"total":240},"livenessData":{"cur":80,"total":100},'
            '"storeEnergyData":{"cur":10,"total":480},"towerData":{"cur":18,"total":30}}}'
        )

    monkeypatch.setattr("qqbot_app.wuwa_service.request.urlopen", fake_urlopen)

    answer = service.get_profile_summary("u1")

    assert isinstance(answer, BotMessage)
    assert "昵称：漂泊者" in answer.content
    assert "结晶波片：120/240" in answer.content
    assert answer.image.startswith(b"\x89PNG")


def test_character_query_fetches_detail_with_character_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = WuwaService(str(tmp_path))
    service.bind_token("u1", "token-1")
    service.bind_role("u1", "101234567")
    calls = []
    responses = [
        json.dumps(
            {
                "code": 200,
                "data": [
                    {
                        "roleName": "漂泊者",
                        "roleId": "101234567",
                        "serverId": WUWA_CN_SERVER_ID,
                        "userId": "bbs-1",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        json.dumps({"code": 200, "data": json.dumps({"accessToken": "access-1"})}),
        '{"code":200,"data":{}}',
        json.dumps(
            {
                "code": 200,
                "data": json.dumps(
                    {"roleList": [{"roleName": "今汐", "roleId": "char-123"}]},
                    ensure_ascii=False,
                ),
            },
            ensure_ascii=False,
        ),
        json.dumps(
            {"code": 200, "data": _encrypt_kuro_data({"roleName": "今汐", "level": 90, "echoList": []})}
        ),
    ]

    def fake_urlopen(req: object, timeout: int = 10) -> _Response:
        calls.append(req)
        return _Response(responses.pop(0))

    monkeypatch.setattr("qqbot_app.wuwa_service.request.urlopen", fake_urlopen)

    answer = service.get_character_summary("u1", "今汐")

    list_body = parse.parse_qs(calls[3].data.decode("utf-8"))
    detail_body = parse.parse_qs(calls[4].data.decode("utf-8"))
    assert calls[0].full_url.endswith("/user/role/findRoleList")
    assert calls[1].full_url.endswith("/aki/roleBox/requestToken")
    assert calls[2].full_url.endswith("/aki/roleBox/akiBox/refreshData")
    assert calls[3].full_url.endswith("/aki/roleBox/akiBox/roleData")
    assert "id" not in list_body
    assert calls[4].full_url.endswith("/aki/roleBox/akiBox/getRoleDetail")
    assert detail_body["roleId"] == ["101234567"]
    assert detail_body["id"] == ["char-123"]
    assert isinstance(answer, BotMessage)
    assert "鸣潮练度：今汐" in answer.content
    assert answer.image.startswith(b"\x89PNG")


def test_token_expired_returns_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = WuwaService(str(tmp_path))
    service.bind_token("u1", "token-1")
    service.bind_role("u1", "101234567")

    def fake_urlopen(req: object, timeout: int = 10) -> _Response:
        return _Response('{"code":220,"msg":"token invalid"}')

    monkeypatch.setattr("qqbot_app.wuwa_service.request.urlopen", fake_urlopen)

    assert service.get_profile_summary("u1") == "鸣潮 Token 已失效，请重新绑定。"


def test_http_error_returns_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = WuwaService(str(tmp_path))
    service.bind_token("u1", "token-1")
    service.bind_role("u1", "101234567")

    def fake_urlopen(req: object, timeout: int = 10) -> _Response:
        raise error.HTTPError("", 429, "rate limit", {}, None)

    monkeypatch.setattr("qqbot_app.wuwa_service.request.urlopen", fake_urlopen)

    assert service.get_profile_summary("u1") == "鸣潮接口请求过于频繁，请稍后再试。"


def test_import_gacha_json_and_analysis(tmp_path: Path) -> None:
    service = WuwaService(str(tmp_path))

    import_answer = service.import_gacha_json(
        "u1",
        '[{"cardPoolType":"1","resourceId":"a","qualityLevel":3,"name":"迅刀","time":"2026-01-01 10:00:00"},'
        '{"cardPoolType":"1","resourceId":"b","qualityLevel":5,"name":"今汐","time":"2026-01-01 10:01:00"},'
        '{"cardPoolType":"2","resourceId":"c","qualityLevel":4,"name":"武器","time":"2026-01-01 10:02:00"}]',
    )
    analysis = service.get_gacha_analysis("u1")

    assert import_answer == "已导入鸣潮抽卡记录 3 条，当前共 3 条。"
    assert isinstance(analysis, BotMessage)
    assert "总抽数：3" in analysis.content
    assert "五星：1" in analysis.content
    assert "四星：1" in analysis.content
    assert "角色活动: 2" in analysis.content
    assert analysis.image.startswith(b"\x89PNG")


def test_import_gacha_json_deduplicates(tmp_path: Path) -> None:
    service = WuwaService(str(tmp_path))
    raw = '[{"cardPoolType":"1","resourceId":"a","qualityLevel":5,"name":"今汐","time":"2026-01-01"}]'

    first = service.import_gacha_json("u1", raw)
    second = service.import_gacha_json("u1", raw)

    assert first == "已导入鸣潮抽卡记录 1 条，当前共 1 条。"
    assert second == "已导入鸣潮抽卡记录 0 条，当前共 1 条。"


def test_import_gacha_url_fetches_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = WuwaService(str(tmp_path))
    calls = []

    def fake_urlopen(req: object, timeout: int = 10) -> _Response:
        calls.append(req)
        if len(calls) == 1:
            return _Response('{"code":200,"data":[{"cardPoolType":"1","resourceId":"a","qualityLevel":5,"name":"今汐","time":"2026"}]}')
        return _Response('{"code":200,"data":[]}')

    monkeypatch.setattr("qqbot_app.wuwa_service.request.urlopen", fake_urlopen)

    answer = service.import_gacha_url(
        "u1",
        "https://aki-gm-resources.aki-game.com/aki/gacha/index.html#/record?"
        "svr_id=76402e5b20be2c39f095a152090afddc&player_id=101234567&lang=zh-Hans&"
        "record_id=record-1&resources_id=pool-1&svr_area=cn",
    )

    assert answer == "已导入鸣潮抽卡记录 1 条，当前共 1 条。"


def test_parse_wuwa_commands() -> None:
    assert parse_wuwa_command("鸣潮登录：13800138000").action == "request_sms"
    assert parse_wuwa_command("鸣潮验证码：123456").action == "submit_sms"
    assert parse_wuwa_command("绑定鸣潮Token：abc").action == "bind_token"
    role = parse_wuwa_command("绑定鸣潮角色：101234567")
    assert role.action == "bind_role"
    assert role.server_id == WUWA_CN_SERVER_ID
    assert parse_wuwa_command("鸣潮面板").action == "profile"
    assert parse_wuwa_command("练度：今汐").action == "character"
    assert parse_wuwa_command("导入鸣潮抽卡JSON：[]").action == "import_gacha_json"
    assert parse_wuwa_command("抽卡分析：角色活动").action == "gacha_analysis"


def test_score_commands_are_not_supported() -> None:
    assert parse_wuwa_command("矩阵分数：今汐") is None
    assert parse_wuwa_command("声骸分数：今汐") is None


def test_parse_invalid_wuwa_command() -> None:
    command = parse_wuwa_command("绑定鸣潮")

    assert command is not None
    assert command.action == "invalid"


def test_format_character_summary() -> None:
    character = {
        "roleName": "今汐",
        "level": 90,
        "chainLevel": 2,
        "weapon": {"weaponName": "时和岁稔", "level": 90},
        "skillList": [{"skillName": "常态攻击", "skillLevel": 10}],
        "echoList": [{"echoName": "角", "level": 25, "rarity": 5, "mainStat": "暴击", "subStats": [{"name": "暴击"}]}],
    }

    summary = format_character_summary(character)
    assert "鸣潮练度：今汐" in summary
    assert "武器：时和岁稔 90" in summary


def test_format_character_handles_current_kuro_schema() -> None:
    character = {
        "level": 90,
        "role": {"roleName": "今汐", "breach": 6},
        "chainList": [{"unlocked": True}, {"unlocked": False}],
        "weaponData": {"level": 90, "weapon": {"weaponName": "时和岁稔"}},
        "skillList": [{"level": 10, "skill": {"name": "共鸣技能"}}],
        "phantomData": {
            "equipPhantomList": [
                {
                    "level": 25,
                    "quality": 5,
                    "phantomProp": {"name": "角"},
                    "mainProps": [{"attributeName": "暴击"}],
                    "subProps": [{"attributeName": "暴击伤害"}],
                }
            ]
        },
    }

    summary = format_character_summary(character)
    assert "鸣潮练度：今汐" in summary
    assert "突破/阶级：6" in summary
    assert "共鸣链：1" in summary
    assert "武器：时和岁稔 90" in summary
    assert "声骸：1 个" in summary


def test_format_profile_summary_handles_missing_data() -> None:
    assert "昵称：-" in format_profile_summary({"data": {}})


def test_format_gacha_analysis_filters_pool() -> None:
    answer = format_gacha_analysis(
        [{"cardPoolType": "1", "qualityLevel": 5, "name": "今汐", "time": "1"}],
        "武器活动",
    )

    assert answer == "没有找到“武器活动”对应的鸣潮抽卡记录。"
