"""A2 标签同义词归并。

用户/导入数据里的别名（如"拍照""出片"）统一归到标准标签 code（photospot），
保证筛选与个性化偏好命中口径一致。同义词表由管理端维护。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Tag, TagSynonym
from app.services.cache import TTLCache

_syn_cache = TTLCache(ttl_seconds=60, max_items=8)


def invalidate() -> None:
    _syn_cache.invalidate_prefix("")


def synonym_map(db: Session) -> dict[str, str]:
    """alias → canonical_code（含标准 code 自身映射，便于统一处理）。"""
    snap = _syn_cache.get("map")
    if snap is not None:
        return snap
    mapping: dict[str, str] = {}
    for alias, code in db.query(TagSynonym.alias, TagSynonym.canonical_code).all():
        if alias and code:
            mapping[alias.strip()] = code.strip()
    _syn_cache.set("map", mapping)
    return mapping


def resolve_codes(db: Session, codes: list[str] | None) -> list[str]:
    """把请求里的别名归并为标准 code，去重且保持顺序。"""
    if not codes:
        return []
    mapping = synonym_map(db)
    out: list[str] = []
    for raw in codes:
        code = (raw or "").strip()
        if not code:
            continue
        canon = mapping.get(code, code)
        if canon not in out:
            out.append(canon)
    return out


def list_synonyms(db: Session) -> list[dict]:
    rows = db.query(TagSynonym).order_by(TagSynonym.id).all()
    tag_names = {t.code: t.name for t in db.query(Tag).all()}
    return [dict(
        id=r.id, alias=r.alias, canonical_code=r.canonical_code,
        canonical_name=tag_names.get(r.canonical_code, ""),
        note=r.note or "",
    ) for r in rows]


def create_synonym(db: Session, alias: str, canonical_code: str, note: str = "") -> dict:
    alias = (alias or "").strip()
    canonical_code = (canonical_code or "").strip()
    if not alias or not canonical_code:
        raise ValueError("别名与标准标签 code 均不能为空")
    if alias == canonical_code:
        raise ValueError("别名不能与标准标签相同")
    if db.query(Tag).filter(Tag.code == canonical_code).first() is None:
        raise ValueError(f"标准标签不存在: {canonical_code}")
    if db.query(TagSynonym).filter(TagSynonym.alias == alias).first():
        raise ValueError(f"别名已存在: {alias}")
    row = TagSynonym(alias=alias, canonical_code=canonical_code, note=note or "")
    db.add(row)
    db.commit()
    invalidate()
    return dict(id=row.id, alias=row.alias, canonical_code=row.canonical_code)


def delete_synonym(db: Session, synonym_id: int) -> bool:
    row = db.get(TagSynonym, synonym_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    invalidate()
    return True


def merge_tag(db: Session, from_code: str, to_code: str) -> dict:
    """把 from_code 标签下挂载的 POI 全部改挂到 to_code，并登记同义词。

    用于历史脏数据治理：合并后 from_code 标签行可保留为空壳，也可由管理员删除。
    """
    from app.models import PoiTag

    src = db.query(Tag).filter(Tag.code == from_code).first()
    dst = db.query(Tag).filter(Tag.code == to_code).first()
    if src is None or dst is None:
        raise ValueError("源标签或目标标签不存在")
    if src.id == dst.id:
        raise ValueError("源与目标标签相同")

    moved = 0
    existing = {
        pid for (pid,) in db.query(PoiTag.poi_id).filter(PoiTag.tag_id == dst.id).all()
    }
    for link in db.query(PoiTag).filter(PoiTag.tag_id == src.id).all():
        if link.poi_id in existing:
            db.delete(link)
        else:
            link.tag_id = dst.id
            existing.add(link.poi_id)
            moved += 1
    if src.code != dst.code and not db.query(TagSynonym).filter(
        TagSynonym.alias == src.code
    ).first():
        db.add(TagSynonym(alias=src.code, canonical_code=dst.code, note="合并自动登记"))
    db.commit()
    invalidate()
    return dict(moved=moved, from_code=from_code, to_code=to_code)
