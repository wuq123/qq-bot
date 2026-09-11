from io import BytesIO

from PIL import Image

from qqbot_app.wuwa_renderer import render_character_card, render_text_card


def test_render_character_card_returns_png() -> None:
    data = {
        "level": 90,
        "role": {"roleName": "今汐", "attributeName": "衍射", "breach": 6, "starLevel": 5},
        "chainList": [{"unlocked": True}, {"unlocked": False}],
        "roleAttributeList": [{"attributeName": "攻击", "attributeValue": "2180"}],
        "weaponData": {
            "level": 90,
            "resonLevel": 1,
            "weapon": {"weaponName": "时和岁稔", "weaponStarLevel": 5},
        },
        "phantomData": {
            "equipPhantomList": [
                {
                    "level": 25,
                    "quality": 5,
                    "phantomProp": {"name": "角", "cost": 4},
                    "mainProps": [{"attributeName": "暴击", "attributeValue": "22%"}],
                    "subProps": [{"attributeName": "暴击伤害", "attributeValue": "15%"}],
                }
            ]
        },
        "skillList": [{"level": 10, "skill": {"name": "共鸣技能", "type": "共鸣技能"}}],
    }

    result = render_character_card(data)
    image = Image.open(BytesIO(result))

    assert result.startswith(b"\x89PNG")
    assert image.size == (1200, 1500)


def test_render_text_card_returns_png() -> None:
    result = render_text_card("鸣潮面板", "昵称：漂泊者\n结晶波片：120/240")
    image = Image.open(BytesIO(result))

    assert result.startswith(b"\x89PNG")
    assert image.width == 1000
    assert image.height >= 420
