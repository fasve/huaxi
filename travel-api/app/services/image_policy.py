"""POI 图片策略：**只展示本地自有素材**。

背景（2026-11-11 产品决定，两次调整后的最终口径）：
1. 联网图库（Wikimedia / Openverse / Pixabay / Pexels）与外部直链本地化全部停用；
2. 允许三类来源对外展示：
   - `upload`：管理员在管理端本地上传（含 `scripts/collect_poi_images.py` 走同一上传接口）；
   - `legacy_local`：`static/poi/` 里的历史存量文件，经
     `scripts/adopt_local_legacy_images.py` 认领回原 POI，**授权未核实**，仅限本地演示；
   - `generated-cover`：`scripts/fill_cover_images.py` 生成的无版权分类封面（抽象图形 SVG），
     仅用于扩容后还没有实拍图的 POI，**不是实景照片**，不作为"已配图"对外宣称。
3. `placeholder`（旧版占位 SVG）不再展示，避免用假图冒充实拍。

没图的 POI 会回落到占位样式（小程序是淡底 + 名称前两字，PC 端是两字色块），不会裂图。
"""
from __future__ import annotations

UPLOAD_SOURCE = "upload"
LEGACY_LOCAL_SOURCE = "legacy_local"
GENERATED_COVER_SOURCE = "generated-cover"
ALLOWED_SOURCES = {UPLOAD_SOURCE, LEGACY_LOCAL_SOURCE, GENERATED_COVER_SOURCE}

# 已停用的来源，仅用于给管理端/脚本生成提示文案
DISABLED_SOURCES: dict[str, str] = {
    "legacy": "历史抓取（未经认领的裸 legacy）",
    "wikimedia": "Wikimedia Commons",
    "openverse": "Openverse",
    "pixabay": "Pixabay",
    "pexels": "Pexels",
    "remote": "外部直链本地化",
    "placeholder": "自动生成的占位图",
}


def is_visible(meta: dict | None) -> bool:
    """该条图片是否允许对外展示。"""
    return bool(meta) and (meta or {}).get("source") in ALLOWED_SOURCES


def split_visible_images(
    images: list | None, metas: list | None,
) -> tuple[list[str], list[dict]]:
    """过滤出可展示的图片，保证 images 与 image_meta 仍然同序对应。

    `image_meta` 历史上允许缺失（老数据），缺失一律视为不可展示，避免脏数据穿透。
    """
    imgs = list(images or [])
    meta_list = list(metas or [])
    out_images: list[str] = []
    out_meta: list[dict] = []
    for i, url in enumerate(imgs):
        if not url:
            continue
        meta = meta_list[i] if i < len(meta_list) else None
        if is_visible(meta):
            out_images.append(url)
            out_meta.append(meta)  # type: ignore[arg-type]
    return out_images, out_meta


def policy_payload() -> dict:
    """给管理端「系统设置」展示的图片策略说明。"""
    return dict(
        sources=sorted(ALLOWED_SOURCES),
        upload_only=False,
        disabled=list(DISABLED_SOURCES.values()),
        message=("图片只允许管理员本地上传；static/poi 的历史存量图已标记 legacy_local 并恢复展示，"
                 "授权未核实，商用前需替换为已授权素材。"),
    )
