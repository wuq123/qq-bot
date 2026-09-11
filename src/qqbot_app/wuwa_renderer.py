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

    draw.rounded_rectangle((34, 32, 1166, 490), radius=34, fill=(16, 34, 44, 220), outline=(86, 224, 197, 90), width=2)
    art = assets.get(art_url)
    if art:
        _paste_contain(image, art, (600, 38, 1140, 486), fade=True)
    draw.text((72, 72), "鸣潮角色练度", font=_font(28), fill=ACCENT)
    draw.text((70, 116), name, font=_font(66, bold=True), fill=TEXT)
    draw.text(
        (74, 204),
        f"{role.get('attributeName') or '-'}  ·  LV.{data.get('level') or role.get('level') or '-'}  ·  "
        f"{_unlocked_chains(data.get('chainList'))} 链",
        font=_font(26),
        fill=MUTED,
    )
    _draw_attributes(draw, data.get("roleAttributeList"), 70, 282)

    _section_title(draw, "武器", 520)
    draw.rounded_rectangle((44, 566, 1156, 720), radius=24, fill=PANEL)
    weapon_icon = assets.get(weapon_url)
    if weapon_icon:
        _paste_contain(image, weapon_icon, (66, 580, 192, 706))
    draw.text((220, 590), str(weapon.get("weaponName") or "未装备武器"), font=_font(34, bold=True), fill=TEXT)
    draw.text(
        (220, 642),
        f"LV.{weapon_data.get('level') or '-'}  ·  精炼 {weapon_data.get('resonLevel') or '-'}  ·  "
        f"{weapon.get('weaponStarLevel') or '-'} 星",
        font=_font(24),
        fill=GOLD,
    )

    _section_title(draw, "声骸", 750)
    if not echoes:
        draw.rounded_rectangle((44, 796, 1156, 1150), radius=24, fill=PANEL)
        draw.text((80, 840), "暂无已装备声骸", font=_font(30), fill=MUTED)
    else:
        _draw_echoes(image, draw, echoes[:5], echo_urls, assets)

    _section_title(draw, "共鸣技能", 1230)
    _draw_skills(image, draw, skills[:5], skill_urls, assets)
    draw.text((44, 1460), "数据来源：库街区 · 图片由机器人实时生成", font=_font(19), fill=(150, 168, 180))
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
        left = x + column * 250
        top = y + row * 52
        draw.text((left, top), str(item.get("attributeName") or "属性"), font=_font(21), fill=MUTED)
        draw.text((left + 112, top), str(item.get("attributeValue") or "-"), font=_font(22, bold=True), fill=TEXT)


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
        draw.rounded_rectangle((x, 796, x + width, 1188), radius=22, fill=PANEL)
        icon = assets.get(urls[index]) if index < len(urls) else None
        if icon:
            _paste_contain(image, icon, (x + 43, 812, x + 171, 940))
        prop = _dict(echo.get("phantomProp"))
        name = str(prop.get("name") or echo.get("echoName") or "声骸")
        draw.text((x + 16, 950), _truncate(name, 8), font=_font(23, bold=True), fill=TEXT)
        echo_level = echo.get("level") or 0
        echo_cost = prop.get("cost") or echo.get("cost") or "-"
        draw.text((x + 16, 986), f"+{echo_level}  COST {echo_cost}", font=_font(19), fill=GOLD)
        props = _list(echo.get("mainProps")) + _list(echo.get("subProps"))
        top = 1024
        for item in props[:5]:
            label = _truncate(str(item.get("attributeName") or "-"), 6)
            value = str(item.get("attributeValue") or "-")
            draw.text((x + 16, top), label, font=_font(17), fill=MUTED)
            draw.text((x + 128, top), value, font=_font(17, bold=True), fill=TEXT)
            top += 29


def _draw_skills(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    skills: List[Dict[str, Any]],
    urls: List[str],
    assets: Dict[str, Image.Image],
) -> None:
    if not skills:
        draw.text((48, 1280), "暂无技能数据", font=_font(25), fill=MUTED)
        return
    for index, item in enumerate(skills):
        x = 48 + index * 224
        skill = _dict(item.get("skill"))
        icon = assets.get(urls[index]) if index < len(urls) else None
        if icon:
            _paste_contain(image, icon, (x, 1276, x + 76, 1352))
        skill_name = _truncate(str(skill.get("type") or skill.get("name") or "技能"), 8)
        draw.text((x, 1362), skill_name, font=_font(18), fill=MUTED)
        draw.text((x, 1392), f"等级 {item.get('level') or '-'}", font=_font(21, bold=True), fill=TEXT)


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
        color = (8 + int(8 * ratio), 20 + int(18 * ratio), 28 + int(20 * ratio))
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


def _section_title(draw: ImageDraw.ImageDraw, title: str, y: int) -> None:
    draw.text((44, y), title, font=_font(29, bold=True), fill=TEXT)
    draw.line((132, y + 23, 1156, y + 23), fill=(86, 224, 197, 70), width=2)


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
