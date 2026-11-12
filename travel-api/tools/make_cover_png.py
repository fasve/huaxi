"""生成 8 套 POI 分类封面（1200×675 PNG，纯 Pillow 绘制，不含任何版权素材）。

为什么用 PNG 而不是 SVG：小程序 `<image>` 对 SVG 支持不稳定（开发者工具直接显示裂图），
而且这批封面要同时给小程序 / PC / 管理端用，PNG 是唯一全端可靠的格式。

用法：
    python tools/make_cover_png.py          # 覆盖生成 8 张
输出：
    static/poi/covers/{nature,mountain,heritage,night,campus,food,hotel,leisure}.png
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "static" / "poi" / "covers"
W, H = 1200, 675
SS = 2  # 超采样倍数，缩回 1x 得到抗锯齿边缘


def hexrgb(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def gradient(size: tuple[int, int], top: str, bottom: str) -> Image.Image:
    w, h = size
    base = Image.new("RGB", (1, h))
    c1, c2 = hexrgb(top), hexrgb(bottom)
    for y in range(h):
        t = y / max(1, h - 1)
        base.putpixel((0, y), tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)))
    return base.resize((w, h), Image.BILINEAR)


def sun(d: ImageDraw.ImageDraw, x: int, y: int, r: int, color: str, alpha: int = 230) -> None:
    d.ellipse([x - r, y - r, x + r, y + r], fill=hexrgb(color) + (alpha,))


def mountains(d: ImageDraw.ImageDraw, pts: list[tuple[int, int]], color: str, alpha: int = 255) -> None:
    d.polygon(pts + [(pts[-1][0], H), (pts[0][0], H)], fill=hexrgb(color) + (alpha,))


def hill(d: ImageDraw.ImageDraw, y: int, color: str, amp: int = 60, alpha: int = 255) -> None:
    steps = 24
    pts = [(0, H)]
    for i in range(steps + 1):
        x = W * i / steps
        yy = y + int(amp * ((i % 2) - 0.5) * 0.6)
        pts.append((x, yy))
    pts.append((W, H))
    d.polygon(pts, fill=hexrgb(color) + (alpha,))


def trees(d: ImageDraw.ImageDraw, base_y: int, xs: list[int], color: str, scale: float = 1.0) -> None:
    """三层的针叶树：树干 + 三层三角，比单三角更像树。"""
    for x in xs:
        h = int(200 * scale)
        w = int(64 * scale)
        trunk_w = max(6, int(14 * scale))
        d.rectangle([x - trunk_w // 2, base_y - int(h * 0.2), x + trunk_w // 2, base_y],
                    fill=hexrgb("#6b5641") + (255,))
        for layer in range(3):
            top = base_y - h + int(h * 0.26 * layer)
            half = int(w * (0.55 + 0.2 * layer))
            bot = top + int(h * 0.44)
            d.polygon([(x, top), (x - half, bot), (x + half, bot)], fill=hexrgb(color) + (255,))


def buildings(d: ImageDraw.ImageDraw, ground: int, color: str, roof: str) -> None:
    specs = [(150, 210, 170), (420, 260, 220), (760, 200, 190)]
    for x, w, h in specs:
        d.rectangle([x, ground - h, x + w, ground], fill=hexrgb(color) + (255,))
        d.polygon([(x - 18, ground - h), (x + w // 2, ground - h - 60), (x + w + 18, ground - h)],
                  fill=hexrgb(roof) + (255,))
        for i in range(2):
            wx = x + 26 + i * (w - 52) // 1
            d.rectangle([wx, ground - h + 34, wx + 40, ground - h + 78],
                        fill=hexrgb("#f6efd8") + (235,))


def theme_nature() -> Image.Image:
    img = gradient((W * SS, H * SS), "#dff1e3", "#a8d5b5").convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    sun(d, 900 * SS, 150 * SS, 64 * SS, "#fff6d8")
    hill(d, 470 * SS, "#79b78d", amp=50 * SS)
    hill(d, 545 * SS, "#4f9670", amp=38 * SS)
    trees(d, 560 * SS, [140 * SS, 250 * SS, 980 * SS], "#2f6b4c", 0.9)
    return img


def theme_mountain() -> Image.Image:
    img = gradient((W * SS, H * SS), "#e4edf4", "#9db8c9").convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    sun(d, 240 * SS, 150 * SS, 56 * SS, "#fff3cf")
    mountains(d, [(0, 470 * SS), (250 * SS, 250 * SS), (470 * SS, 470 * SS)], "#6f93a8")
    mountains(d, [(300 * SS, 470 * SS), (640 * SS, 215 * SS), (980 * SS, 470 * SS)], "#5b7f96")
    mountains(d, [(720 * SS, 470 * SS), (1010 * SS, 300 * SS), (1200 * SS, 470 * SS)], "#3f657c")
    hill(d, 540 * SS, "#2f5568", amp=26 * SS)
    return img


def theme_heritage() -> Image.Image:
    img = gradient((W * SS, H * SS), "#f3e7d6", "#d9bb98").convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    sun(d, 950 * SS, 140 * SS, 54 * SS, "#fdf0cc")
    buildings(d, 540 * SS, "#8a5a3b", "#6f4529")
    d.rectangle([0, 540 * SS, W * SS, H * SS], fill=hexrgb("#c9a97f") + (255,))
    return img


def theme_night() -> Image.Image:
    img = gradient((W * SS, H * SS), "#22314a", "#4d6382").convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    sun(d, 900 * SS, 150 * SS, 62 * SS, "#f4f1c9", 245)
    for x, y, r in [(160, 110, 3), (300, 200, 2), (520, 90, 2), (680, 170, 3), (1040, 240, 2)]:
        d.ellipse([(x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS],
                  fill=(255, 255, 255, 210))
    mountains(d, [(0, 500 * SS), (260 * SS, 300 * SS), (520 * SS, 500 * SS)], "#2c3d55")
    mountains(d, [(380 * SS, 520 * SS), (700 * SS, 330 * SS), (1040 * SS, 520 * SS)], "#20304a")
    hill(d, 560 * SS, "#16233a", amp=22 * SS)
    return img


def theme_campus() -> Image.Image:
    img = gradient((W * SS, H * SS), "#eef3ea", "#c8d9c4").convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    sun(d, 970 * SS, 140 * SS, 50 * SS, "#fbf6dd")
    # 主楼 + 门廊柱
    d.rectangle([300 * SS, 250 * SS, 900 * SS, 560 * SS], fill=hexrgb("#8a7a63") + (255,))
    d.polygon([(270 * SS, 250 * SS), (600 * SS, 170 * SS), (930 * SS, 250 * SS)],
              fill=hexrgb("#6f6250") + (255,))
    for i in range(5):
        x = 350 * SS + i * 100 * SS
        d.rectangle([x, 300 * SS, x + 46 * SS, 560 * SS], fill=hexrgb("#efe6d3") + (235,))
    d.rectangle([0, 560 * SS, W * SS, H * SS], fill=hexrgb("#9dbb95") + (255,))
    trees(d, 600 * SS, [140 * SS, 1050 * SS], "#3f6b4a", 0.85)
    return img


def theme_food() -> Image.Image:
    img = gradient((W * SS, H * SS), "#f8e9dc", "#e9c3a0").convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    sun(d, 960 * SS, 140 * SS, 46 * SS, "#fdf1d8")
    # 碗 + 面条 + 热气
    d.arc([330 * SS, 300 * SS, 870 * SS, 660 * SS], 0, 180, fill=hexrgb("#b4552f") + (255,),
          width=26 * SS)
    d.chord([330 * SS, 300 * SS, 870 * SS, 620 * SS], 0, 180, fill=hexrgb("#fdf5ea") + (255,))
    for i in range(4):
        x = 420 * SS + i * 90 * SS
        d.arc([x, 330 * SS, x + 70 * SS, 400 * SS], 200, 340, fill=hexrgb("#e0a55c") + (255,),
              width=10 * SS)
    for i in range(3):
        x = 500 * SS + i * 110 * SS
        d.arc([x, 230 * SS, x + 60 * SS, 330 * SS], 250, 380, fill=(255, 255, 255, 160),
              width=9 * SS)
    return img


def theme_hotel() -> Image.Image:
    img = gradient((W * SS, H * SS), "#e9e6f4", "#b9b1d6").convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    sun(d, 940 * SS, 140 * SS, 48 * SS, "#fdf6e0")
    d.rectangle([250 * SS, 210 * SS, 950 * SS, 560 * SS], fill=hexrgb("#6d6485") + (255,))
    for row in range(3):
        for col in range(5):
            x = 300 * SS + col * 130 * SS
            y = 270 * SS + row * 95 * SS
            lit = (row + col) % 3 != 0
            d.rectangle([x, y, x + 76 * SS, y + 56 * SS],
                        fill=hexrgb("#f7e9bd" if lit else "#4d4663") + (255,))
    d.rectangle([0, 560 * SS, W * SS, H * SS], fill=hexrgb("#8f87a8") + (255,))
    return img


def theme_leisure() -> Image.Image:
    img = gradient((W * SS, H * SS), "#e6f2f6", "#9fc6d6").convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    sun(d, 930 * SS, 150 * SS, 52 * SS, "#fff8dc")
    # 帐篷 + 吊床
    d.polygon([(600 * SS, 260 * SS), (330 * SS, 560 * SS), (870 * SS, 560 * SS)],
              fill=hexrgb("#e08a4a") + (255,))
    d.polygon([(600 * SS, 320 * SS), (430 * SS, 560 * SS), (600 * SS, 560 * SS)],
              fill=hexrgb("#c56f34") + (255,))
    d.line([(150 * SS, 430 * SS), (1050 * SS, 430 * SS)], fill=hexrgb("#8a6a4a") + (255,),
           width=8 * SS)
    trees(d, 560 * SS, [140 * SS, 1060 * SS], "#3f7a58", 0.9)
    hill(d, 600 * SS, "#6fa98a", amp=20 * SS)
    return img


THEMES = {
    "nature": theme_nature,
    "mountain": theme_mountain,
    "heritage": theme_heritage,
    "night": theme_night,
    "campus": theme_campus,
    "food": theme_food,
    "hotel": theme_hotel,
    "leisure": theme_leisure,
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, fn in THEMES.items():
        img = fn().convert("RGB").resize((W, H), Image.LANCZOS)
        img = img.filter(ImageFilter.SMOOTH)
        out = OUT_DIR / f"{name}.png"
        img.save(out, "PNG", optimize=True)
        print(f"{name:<10} -> {out.name:<14} {out.stat().st_size:>7} bytes  {img.size}")
    print("完成：", len(THEMES), "张 PNG 封面")


if __name__ == "__main__":
    main()
