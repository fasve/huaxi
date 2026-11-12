#!/usr/bin/env python3
"""生成 tabBar 线性图标（81×81 PNG，两套颜色：常态 / 选中）。

做法：在 4 倍画布（324×324）上画，再 LANCZOS 缩到 81×81，保证边缘抗锯齿；
线条统一 22px@4x（≈5.5px@1x），端点圆头，视觉重量与 30rpx 字号的 tab 文字匹配。

用法：python tools/make_tab_icons.py
输出：assets/tabbar/{home,discover,plan,mine}[-on].png
"""
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 324          # 4x 画布
OUT = 81            # 微信 tabBar 推荐 81×81
W = 22              # 线宽（4x）
NORMAL = (138, 154, 147, 255)   # #8A9A93
ACTIVE = (47, 125, 92, 255)     # #2F7D5C

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "assets" / "tabbar"


def canvas():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def cap(d, x, y, color, r=None):
    """圆头端点：PIL 的 line 没有 cap 参数，用同色圆补一个。"""
    r = W // 2 if r is None else r
    d.ellipse([(x - r, y - r), (x + r, y + r)], fill=color)


def home(d, color):
    # 屋顶：一条带圆角的折线 + 两侧圆头端点（实测这版在 81px 下没有台阶）
    d.line([(56, 158), (162, 68), (268, 158)], fill=color, width=W, joint="curve")
    cap(d, 56, 158, color)
    cap(d, 268, 158, color)
    # 屋身
    d.line([(86, 152), (86, 248), (238, 248), (238, 152)], fill=color, width=W, joint="curve")
    # 门
    d.line([(146, 248), (146, 198), (178, 198), (178, 248)], fill=color, width=W, joint="curve")


def discover(d, color):
    # 放大镜：镜圈 + 45° 手柄（小尺寸下比罗盘指针更易辨识）
    d.ellipse([(64, 64), (232, 232)], outline=color, width=W)
    d.line([(206, 206), (252, 252)], fill=color, width=W)
    d.ellipse([(206 - W // 2, 206 - W // 2), (206 + W // 2, 206 + W // 2)], fill=color)
    d.ellipse([(252 - W // 2, 252 - W // 2), (252 + W // 2, 252 + W // 2)], fill=color)


def plan(d, color):
    # 三根滑杆 + 旋钮：表达「可调的定制」
    for y, x in ((104, 120), (162, 208), (220, 148)):
        d.line([(62, y), (262, y)], fill=color, width=W)
        d.ellipse([(x - 26, y - 26), (x + 26, y + 26)], fill=(255, 255, 255, 255),
                  outline=color, width=W)


def mine(d, color):
    # 头
    d.ellipse([(114, 76), (210, 172)], outline=color, width=W)
    # 肩
    d.arc([(70, 176), (254, 356)], start=200, end=340, fill=color, width=W)


ICONS = {"home": home, "discover": discover, "plan": plan, "mine": mine}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, draw in ICONS.items():
        for suffix, color in (("", NORMAL), ("-on", ACTIVE)):
            img, d = canvas()
            draw(d, color)
            img = img.resize((OUT, OUT), Image.LANCZOS)
            path = OUT_DIR / f"{name}{suffix}.png"
            img.save(path)
            print("wrote", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
