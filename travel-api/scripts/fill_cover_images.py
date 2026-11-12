"""为没有实景图的 POI 生成「分类主题封面」SVG（无版权风险，替代空白/占位图）。

用法：
    python scripts/fill_cover_images.py            # 只给没有图的 POI 补封面
    python scripts/fill_cover_images.py --all      # 全部覆盖为分类封面（谨慎：会覆盖实景图）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models import Poi  # noqa: E402
from app.services.cache import poi_cache  # noqa: E402

COVER_DIR = Path(__file__).resolve().parent.parent / "static" / "poi" / "covers"

# 主题 → (配色, 图形元素)；全部抽象图形，不含版权素材
THEMES: dict[str, dict] = {
    "nature": {
        "bg": ("#dff1e3", "#a8d5b5"),
        "shapes": """
  <circle cx="470" cy="96" r="46" fill="#fff6d8" opacity=".9"/>
  <path d="M0 300 Q120 230 250 285 T520 270 T600 300 L600 400 L0 400Z" fill="#79b78d" opacity=".85"/>
  <path d="M0 335 Q150 290 300 330 T600 320 L600 400 L0 400Z" fill="#4f9670"/>
  <path d="M60 342 q60 -12 120 0 M250 350 q60 -12 120 0 M440 344 q60 -12 120 0" stroke="#e8f6ea" stroke-width="5" fill="none" stroke-linecap="round" opacity=".8"/>
  <g fill="#2f6b4c"><path d="M110 300 l16 -46 16 46z"/><path d="M150 306 l12 -34 12 34z"/></g>
""",
    },
    "mountain": {
        "bg": ("#e4edf4", "#9db8c9"),
        "shapes": """
  <circle cx="120" cy="100" r="40" fill="#fff3cf" opacity=".9"/>
  <path d="M0 320 L150 160 L260 300 L360 190 L470 320 L600 210 L600 400 L0 400Z" fill="#6f93a8" opacity=".9"/>
  <path d="M0 360 L120 280 L230 350 L360 270 L470 350 L600 300 L600 400 L0 400Z" fill="#3f657c"/>
  <path d="M150 160 L190 210 L160 205Z" fill="#eef5f8" opacity=".9"/>
  <path d="M360 190 L400 240 L370 235Z" fill="#eef5f8" opacity=".9"/>
""",
    },
    "heritage": {
        "bg": ("#f6e6d2", "#d8b48c"),
        "shapes": """
  <circle cx="480" cy="90" r="38" fill="#fff1d0" opacity=".9"/>
  <g fill="#8a5a3b">
    <path d="M60 300 L140 240 L220 300 L220 400 L60 400Z"/>
    <path d="M80 250 q40 -26 80 0" fill="none" stroke="#6d452c" stroke-width="8"/>
    <path d="M240 320 L320 250 L400 320 L400 400 L240 400Z"/>
    <path d="M255 265 q45 -28 90 0" fill="none" stroke="#6d452c" stroke-width="8"/>
    <rect x="120" y="330" width="34" height="70" fill="#4a2f1e"/>
    <rect x="300" y="345" width="30" height="55" fill="#4a2f1e"/>
  </g>
  <g fill="#a9744a" opacity=".95">
    <rect x="440" y="300" width="120" height="100"/>
    <path d="M420 300 L500 240 L580 300Z"/>
  </g>
  <g fill="#d9a86c"><rect x="460" y="330" width="24" height="24"/><rect x="510" y="330" width="24" height="24"/></g>
""",
    },
    "night": {
        "bg": ("#1f2f46", "#41597a"),
        "shapes": """
  <circle cx="470" cy="100" r="42" fill="#f5e6b8" opacity=".95"/>
  <circle cx="455" cy="92" r="40" fill="#2a3b55" opacity=".55"/>
  <g fill="#0f1c2c">
    <path d="M0 360 L120 250 L240 360 L360 270 L480 360 L600 300 L600 400 L0 400Z" opacity=".9"/>
  </g>
  <g fill="#ffd47a" opacity=".9">
    <rect x="120" y="330" width="14" height="20" rx="3"/><rect x="160" y="345" width="14" height="20" rx="3"/>
    <rect x="300" y="325" width="14" height="20" rx="3"/><rect x="340" y="350" width="14" height="20" rx="3"/>
    <rect x="470" y="335" width="14" height="20" rx="3"/><rect x="510" y="352" width="14" height="20" rx="3"/>
  </g>
""",
    },
    "campus": {
        "bg": ("#e8f0e4", "#bdd4b0"),
        "shapes": """
  <circle cx="120" cy="110" r="38" fill="#fff6d8" opacity=".9"/>
  <g fill="#7f9b6f">
    <rect x="150" y="250" width="300" height="150" rx="6"/>
    <path d="M170 250 q130 -60 260 0" fill="none" stroke="#5d7a4c" stroke-width="14"/>
  </g>
  <g fill="#dfe9d8">
    <rect x="200" y="290" width="46" height="60" rx="4"/><rect x="280" y="290" width="46" height="60" rx="4"/>
    <rect x="360" y="290" width="46" height="60" rx="4"/>
  </g>
  <rect x="270" y="330" width="60" height="70" fill="#5d7a4c"/>
  <g fill="#8fae7c"><circle cx="90" cy="330" r="34" opacity=".85"/><circle cx="540" cy="345" r="30" opacity=".8"/></g>
""",
    },
    "food": {
        "bg": ("#f8e9dc", "#e9c3a0"),
        "shapes": """
  <circle cx="480" cy="96" r="36" fill="#fff3d6" opacity=".9"/>
  <g>
    <ellipse cx="300" cy="300" rx="170" ry="52" fill="#fff8ee"/>
    <path d="M140 300 a160 62 0 0 0 320 0Z" fill="#f0b27a"/>
    <ellipse cx="300" cy="300" rx="140" ry="36" fill="#fff2df"/>
    <path d="M200 296 q40 -26 80 0 q40 26 80 0" stroke="#c98a4b" stroke-width="7" fill="none" stroke-linecap="round"/>
    <ellipse cx="300" cy="300" rx="140" ry="36" fill="none" stroke="#e8c9a6" stroke-width="3"/>
  </g>
  <g stroke="#8a5a3b" stroke-width="8" stroke-linecap="round">
    <path d="M470 250 L540 180"/><path d="M500 268 L570 198"/>
  </g>
  <g fill="#d98a8a"><circle cx="250" cy="298" r="8"/><circle cx="300" cy="304" r="8"/><circle cx="350" cy="298" r="8"/></g>
""",
    },
    "hotel": {
        "bg": ("#e9e6f4", "#b9b1d6"),
        "shapes": """
  <circle cx="120" cy="100" r="36" fill="#fff3d6" opacity=".9"/>
  <rect x="120" y="230" width="360" height="170" rx="8" fill="#8f86b8"/>
  <g fill="#f2eff9">
    <rect x="150" y="260" width="40" height="50" rx="4"/><rect x="215" y="260" width="40" height="50" rx="4"/>
    <rect x="280" y="260" width="40" height="50" rx="4"/><rect x="345" y="260" width="40" height="50" rx="4"/>
    <rect x="410" y="260" width="40" height="50" rx="4"/>
  </g>
  <rect x="240" y="330" width="120" height="70" rx="6" fill="#5f5a80"/>
  <g fill="#7b739e"><rect x="90" y="300" width="90" height="100" rx="6"/><rect x="480" y="310" width="70" height="90" rx="6"/></g>
  <path d="M90 300 L135 260 L180 300Z" fill="#6b648c"/>
""",
    },
    "leisure": {
        "bg": ("#e7f2ec", "#b2d6c4"),
        "shapes": """
  <circle cx="470" cy="100" r="40" fill="#fff3d0" opacity=".9"/>
  <path d="M0 340 Q150 280 300 330 T600 320 L600 400 L0 400Z" fill="#79b78d"/>
  <g stroke="#3f7a5c" stroke-width="7" stroke-linecap="round" fill="none">
    <path d="M140 340 L140 250"/><path d="M140 250 Q100 280 90 320"/><path d="M140 250 Q180 280 190 320"/>
    <path d="M300 345 L300 265"/><path d="M300 265 Q260 295 250 330"/><path d="M300 265 Q340 295 350 330"/>
  </g>
  <g fill="#2f6b4c"><circle cx="140" cy="245" r="26"/><circle cx="300" cy="260" r="24"/></g>
  <path d="M420 340 q60 -14 120 0" stroke="#e8f6ea" stroke-width="5" fill="none" opacity=".8"/>
""",
    },
}

THEME_LABEL = {
    "nature": "湿地田园", "mountain": "山水山林", "heritage": "古镇人文",
    "night": "夜景灯光", "campus": "校园游学", "food": "地方美食",
    "hotel": "住宿休憩", "leisure": "休闲体验",
}


def pick_theme(poi: Poi) -> str:
    cat = (poi.category or "").lower()
    sub = (poi.sub_type or "") + (poi.name or "")
    if cat == "food":
        return "food"
    if cat == "hotel":
        return "hotel"
    if cat == "study" or "校园" in sub or "大学" in sub:
        return "campus"
    if "夜景" in sub or "夜游" in sub or "灯光" in sub:
        return "night"
    if "古镇" in sub or "古街" in sub or "古城" in sub or "阁" in sub or "祠" in sub:
        return "heritage"
    if "山" in sub or "峡谷" in sub or "森林" in sub or "陵" in sub:
        return "mountain"
    if cat == "leisure":
        return "leisure"
    return "nature"


def svg_for(theme: str, key: str) -> str:
    cfg = THEMES[theme]
    c1, c2 = cfg["bg"]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400" viewBox="0 0 600 400" role="img" aria-label="{THEME_LABEL[theme]}">
  <defs>
    <linearGradient id="bg{key}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{c1}"/><stop offset="100%" stop-color="{c2}"/>
    </linearGradient>
  </defs>
  <rect width="600" height="400" fill="url(#bg{key})"/>
  {cfg['shapes']}
  <rect width="600" height="400" fill="none" stroke="#ffffff" stroke-opacity=".25" stroke-width="2"/>
</svg>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="覆盖已有实景图（默认只补空图）")
    args = ap.parse_args()

    COVER_DIR.mkdir(parents=True, exist_ok=True)
    for idx, theme in enumerate(THEMES):
        (COVER_DIR / f"{theme}.svg").write_text(svg_for(theme, idx), encoding="utf-8")

    db = SessionLocal()
    changed, skipped = 0, 0
    try:
        for poi in db.query(Poi).all():
            if not args.all and (poi.images or []):
                skipped += 1
                continue
            theme = pick_theme(poi)
            poi.images = [f"/static/poi/covers/{theme}.svg"]
            # image_meta 必须与 images 同序（list[dict]），不能直接存 dict
            poi.image_meta = [{"source": "generated-cover", "theme": theme,
                               "label": THEME_LABEL[theme], "license": "self-generated"}]
            changed += 1
        db.commit()
    finally:
        db.close()
    print(f"封面主题: {', '.join(THEMES.keys())}")
    print(f"更新 {changed} 条 POI 封面，跳过 {skipped} 条（已有图）")


if __name__ == "__main__":
    main()
