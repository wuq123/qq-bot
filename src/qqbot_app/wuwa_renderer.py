from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib import request

from PIL import Image, ImageDraw, ImageFont

CARD_WIDTH = 1200
CARD_HEIGHT = 1500
ACCENT = "#56E0C5"
GOLD = "#F5C86B"
TEXT = "#F4F7FA"
MUTED = "#AEBBC6"
PANEL = "#172630"


def render_character_card(data: Dict[str, Any]) -> bytes:
    image = _gradient_image(CARD_WIDTH, CARD_HEIGHT)
    draw = ImageDraw.Draw(image, "RGBA")
    role = _dict(data.get("role")) or data
    weapon_data = _dict(data.get("weaponData"))
    weapon = _dict(weapon_data.get("weapon"))
    echoes = _list(_dict(data.get("phantomData")).get("equipPhantomList"))
    skills = [item for item in _list(data.get("skillList")) if _dict(item.get("skill")).get("type") != "延奏技能"]
    name = str(role.get("roleName") or role.get("name") or "未知角色")
    art_url = str(_dict(data.get("roleSkin")).get("picUrl") or role.get("rolePicUrl") or "")
    weapon_url = str(weapon.get("weaponIcon") or "")
    echo_urls = [str(_dict(item.get("phantomProp")).get("iconUrl") or "") for item in echoes[:5]]
    skill_urls = [str(_dict(item.get("skill")).get("iconUrl") or "") for item in skills[:5]]
    assets = _load_images([art_url, weapon_url, *echo_urls, *skill_urls])

    draw.ellipse((760, -180, 1320, 400), fill=(50, 196, 174, 22))
    draw.ellipse((-280, 1040, 420, 1680), fill=(61, 115, 144, 18))
    _draw_panel(draw, (34, 32, 1166, 500), radius=34, outline=(86, 224, 197, 105))
    draw.rounded_rectangle((56, 68, 62, 238), radius=3, fill=ACCENT)
    draw.ellipse((700, 54, 1146, 492), fill=(86, 224, 197, 15), outline=(86, 224, 197, 35), width=2)
    art = assets.get(art_url)
    if art:
        _paste_contain(image, art, (610, 42, 1142, 496), fade=True)
    draw.text((82, 68), "鸣潮 · 角色练度", font=_font(25), fill=ACCENT)
    draw.text((80, 112), _truncate(name, 8), font=_font(62, bold=True), fill=TEXT)
    badge_x = 80
    for label, value in (
        ("属性", role.get("attributeName") or "-"),
        ("等级", f"LV.{data.get('level') or role.get('level') or '-'}"),
        ("共鸣链", f"{_unlocked_chains(data.get('chainList'))} 链"),
    ):
        badge_x += _draw_badge(draw, badge_x, 202, label, str(value)) + 12
    _draw_attributes(draw, data.get("roleAttributeList"), 78, 274)

    _section_title(draw, "武器", "WEAPON", 530)
    _draw_panel(draw, (44, 576, 1156, 726), radius=24, outline=(86, 224, 197, 45))
    draw.rounded_rectangle((64, 592, 190, 710), radius=20, fill=(10, 27, 36, 205), outline=(86, 224, 197, 55), width=2)
    weapon_icon = assets.get(weapon_url)
    if weapon_icon:
        _paste_contain(image, weapon_icon, (68, 594, 186, 708))
    draw.text((220, 598), _truncate(str(weapon.get("weaponName") or "未装备武器"), 18), font=_font(34, bold=True), fill=TEXT)
    weapon_badge_x = 220
    for value in (
        f"LV.{weapon_data.get('level') or '-'}",
        f"精炼 {weapon_data.get('resonLevel') or '-'}",
        f"{weapon.get('weaponStarLevel') or '-'} 星",
    ):
        weapon_badge_x += _draw_value_pill(draw, weapon_badge_x, 658, value) + 12

    _section_title(draw, "声骸", "ECHOES", 758)
    if not echoes:
        _draw_panel(draw, (44, 806, 1156, 1194), radius=24)
        draw.text((80, 850), "暂无已装备声骸", font=_font(30), fill=MUTED)
    else:
        _draw_echoes(image, draw, echoes[:5], echo_urls, assets)

    _section_title(draw, "共鸣技能", "SKILLS", 1232)
    _draw_skills(image, draw, skills[:5], skill_urls, assets)
    draw.text((44, 1468), "数据来源：库街区  ·  图片由机器人实时生成", font=_font(18), fill=(126, 151, 164))
    draw.text((1058, 1468), "WUWA", font=_font(18, bold=True), fill=(86, 224, 197, 135))
    return _to_png(image)


def render_text_card(title: str, text: str) -> bytes:
    lines = [line for line in text.splitlines() if line.strip()]
    height = max(420, 190 + len(lines) * 62)
    image = _gradient_image(1000, height)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle(
        (34, 30, 966, height - 34),
        radius=30,
        fill=(18, 37, 48, 225),
        outline=(86, 224, 197, 90),
        width=2,
    )
    draw.text((72, 66), title, font=_font(44, bold=True), fill=TEXT)
    draw.line((72, 132, 928, 132), fill=(86, 224, 197, 100), width=2)
    y = 164
    for line in lines:
        color = ACCENT if line.endswith("：") else TEXT
        draw.text((76, y), line, font=_font(27), fill=color)
        y += 62
    return _to_png(image)


def _draw_attributes(draw: ImageDraw.ImageDraw, value: Any, x: int, y: int) -> None:
    attributes = _list(value)[:6]
    for index, item in enumerate(attributes):
        column = index % 2
        row = index // 2
        left = x + column * 252
        top = y + row * 62
        draw.rounded_rectangle((left, top, left + 238, top + 50), radius=13, fill=(9, 27, 36, 165))
        draw.text((left + 14, top + 13), _truncate(str(item.get("attributeName") or "属性"), 7), font=_font(18), fill=MUTED)
        _draw_right_text(draw, left + 224, top + 12, str(item.get("attributeValue") or "-"), _font(20, bold=True), TEXT)


def _draw_echoes(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    echoes: List[Dict[str, Any]],
    urls: List[str],
    assets: Dict[str, Image.Image],
) -> None:
    width = 214
    for index, echo in enumerate(echoes):
        x = 44 + index * 224
        _draw_panel(draw, (x, 806, x + width, 1194), radius=22, outline=(86, 224, 197, 32))
        draw.rounded_rectangle((x + 38, 822, x + 176, 952), radius=24, fill=(9, 27, 36, 185))
        icon = assets.get(urls[index]) if index < len(urls) else None
        if icon:
            _paste_contain(image, icon, (x + 43, 826, x + 171, 948))
        prop = _dict(echo.get("phantomProp"))
        name = str(prop.get("name") or echo.get("echoName") or "声骸")
        draw.text((x + 16, 964), _truncate(name, 8), font=_font(23, bold=True), fill=TEXT)
        echo_level = echo.get("level") or 0
        echo_cost = prop.get("cost") or echo.get("cost") or "-"
        draw.rounded_rectangle((x + 14, 1000, x + 200, 1035), radius=11, fill=(245, 200, 107, 18))
        draw.text((x + 24, 1007), f"+{echo_level}  ·  COST {echo_cost}", font=_font(17, bold=True), fill=GOLD)
        props = _list(echo.get("mainProps")) + _list(echo.get("subProps"))
        top = 1051
        for item in props[:5]:
            label = _truncate(str(item.get("attributeName") or "-"), 6)
            value = str(item.get("attributeValue") or "-")
            draw.text((x + 16, top), label, font=_font(17), fill=MUTED)
            _draw_right_text(draw, x + 198, top, value, _font(17, bold=True), TEXT)
            top += 27


def _draw_skills(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    skills: List[Dict[str, Any]],
    urls: List[str],
    assets: Dict[str, Image.Image],
) -> None:
    if not skills:
        draw.text((48, 1284), "暂无技能数据", font=_font(25), fill=MUTED)
        return
    for index, item in enumerate(skills):
        x = 44 + index * 224
        skill = _dict(item.get("skill"))
        icon = assets.get(urls[index]) if index < len(urls) else None
        _draw_panel(draw, (x, 1278, x + 214, 1442), radius=20, outline=(86, 224, 197, 28))
        draw.rounded_rectangle((x + 16, 1294, x + 90, 1368), radius=18, fill=(9, 27, 36, 190))
        if icon:
            _paste_contain(image, icon, (x + 17, 1295, x + 89, 1367))
        skill_name = _truncate(str(skill.get("type") or skill.get("name") or "技能"), 8)
        draw.text((x + 16, 1380), skill_name, font=_font(17), fill=MUTED)
        draw.text((x + 106, 1304), "等级", font=_font(17), fill=MUTED)
        draw.text((x + 106, 1332), str(item.get("level") or "-"), font=_font(26, bold=True), fill=ACCENT)


def _load_images(urls: Iterable[str]) -> Dict[str, Image.Image]:
    unique = [url for url in dict.fromkeys(urls) if url.startswith(("http://", "https://"))]
    if not unique:
        return {}
    with ThreadPoolExecutor(max_workers=min(6, len(unique))) as executor:
        images = list(executor.map(_download_image, unique))
    return {url: image for url, image in zip(unique, images) if image is not None}


def _download_image(url: str) -> Optional[Image.Image]:
    try:
        req = request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with request.urlopen(req, timeout=6) as response:
            data = response.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            return None
        image = Image.open(BytesIO(data))
        image.load()
        return image.convert("RGBA")
    except Exception:
        return None


def _paste_contain(
    target: Image.Image,
    source: Image.Image,
    box: tuple[int, int, int, int],
    fade: bool = False,
) -> None:
    width = box[2] - box[0]
    height = box[3] - box[1]
    source = source.copy()
    source.thumbnail((width, height), Image.Resampling.LANCZOS)
    if fade:
        source.putalpha(source.getchannel("A").point(lambda value: int(value * 0.85)))
    x = box[0] + (width - source.width) // 2
    y = box[1] + (height - source.height) // 2
    target.paste(source, (x, y), source)


def _gradient_image(width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = (7 + int(8 * ratio), 19 + int(17 * ratio), 28 + int(18 * ratio))
        draw.line((0, y, width, y), fill=color)
    return image


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = ["msyhbd.ttc", "msyh.ttc"] if bold else ["msyh.ttc", "msyhl.ttc"]
    paths = [Path("C:/Windows/Fonts") / name for name in names]
    paths.extend(
        [
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        ]
    )
    for path in paths:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _section_title(draw: ImageDraw.ImageDraw, title: str, subtitle: str, y: int) -> None:
    title_font = _font(29, bold=True)
    subtitle_font = _font(17)
    title_width = draw.textlength(title, font=title_font)
    subtitle_x = int(44 + title_width + 30)
    subtitle_width = draw.textlength(subtitle, font=subtitle_font)
    draw.text((44, y), title, font=title_font, fill=TEXT)
    draw.text((subtitle_x, y + 7), subtitle, font=subtitle_font, fill=(86, 224, 197, 145))
    draw.line((subtitle_x + subtitle_width + 32, y + 22, 1156, y + 22), fill=(86, 224, 197, 65), width=2)


def _draw_panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int,
    outline: tuple[int, int, int, int] = (255, 255, 255, 16),
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=(23, 38, 48, 225), outline=outline, width=2)


def _draw_badge(draw: ImageDraw.ImageDraw, x: int, y: int, label: str, value: str) -> int:
    label_font = _font(16)
    value_font = _font(18, bold=True)
    label_width = draw.textlength(label, font=label_font)
    value_width = draw.textlength(value, font=value_font)
    width = int(label_width + value_width + 42)
    draw.rounded_rectangle((x, y, x + width, y + 42), radius=13, fill=(9, 27, 36, 180), outline=(86, 224, 197, 38), width=1)
    draw.text((x + 12, y + 11), label, font=label_font, fill=MUTED)
    draw.text((x + 24 + label_width, y + 9), value, font=value_font, fill=TEXT)
    return width


def _draw_value_pill(draw: ImageDraw.ImageDraw, x: int, y: int, value: str) -> int:
    font = _font(18, bold=True)
    width = int(draw.textlength(value, font=font) + 28)
    draw.rounded_rectangle((x, y, x + width, y + 38), radius=12, fill=(245, 200, 107, 18), outline=(245, 200, 107, 36), width=1)
    draw.text((x + 14, y + 9), value, font=font, fill=GOLD)
    return width


def _draw_right_text(
    draw: ImageDraw.ImageDraw,
    right: int,
    y: int,
    value: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: str,
) -> None:
    draw.text((right - draw.textlength(value, font=font), y), value, font=font, fill=fill)


def _unlocked_chains(value: Any) -> int:
    return sum(1 for item in _list(value) if item.get("unlocked"))


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> List[Dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _truncate(value: str, length: int) -> str:
    return value if len(value) <= length else value[: length - 1] + "…"


def _to_png(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
