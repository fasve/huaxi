"""A4 权重配置版本管理：历史快照、回滚与灰度发布。

- 每次管理端更新模式配置前自动留一份 history 快照，可随时回滚。
- 灰度：candidate 版本带 traffic_pct，按请求 key（生成时用 seed）稳定分桶命中。
- 所有变更都失效 `mode_cache`，线上立即生效。
"""
from __future__ import annotations

import hashlib

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import TripModeConfig, TripModeConfigVersion
from app.services.cache import mode_cache


def _next_version(db: Session, mode: str, cfg: TripModeConfig) -> int:
    latest = (
        db.query(TripModeConfigVersion.version)
        .filter(TripModeConfigVersion.mode == mode)
        .order_by(TripModeConfigVersion.version.desc())
        .first()
    )
    return max(int(cfg.version or 0), int(latest[0]) if latest else 0) + 1


def validate_weights(weights: dict) -> None:
    """权重合法性：兼容「9 维含 budget_fit 合计 1.0」与「8 维静态合计 1.0」两种口径。"""
    w = weights or {}
    total_all = sum(float(v) for v in w.values())
    total_static = sum(float(v) for k, v in w.items() if k != "budget_fit")
    if abs(total_all - 1.0) <= 0.01 or abs(total_static - 1.0) <= 0.01:
        return
    raise HTTPException(
        400, f"权重和必须为 1.0（含/不含 budget_fit 均可），当前 9 维 {total_all:.3f} / 8 维 {total_static:.3f}",
    )


def snapshot(db: Session, cfg: TripModeConfig, status: str = "history",
             traffic_pct: int = 0, note: str = "", commit: bool = False) -> TripModeConfigVersion:
    """把配置当前内容写入版本表（同一 mode+version+status 去重）。"""
    exists = (
        db.query(TripModeConfigVersion)
        .filter(
            TripModeConfigVersion.mode == cfg.mode,
            TripModeConfigVersion.version == cfg.version,
            TripModeConfigVersion.status == status,
        )
        .first()
    )
    if exists is not None:
        return exists
    rec = TripModeConfigVersion(
        mode=cfg.mode, version=int(cfg.version or 1),
        weights=dict(cfg.weights or {}), hard_rules=dict(cfg.hard_rules or {}),
        slot_template=list(cfg.slot_template or []),
        description=cfg.description or "",
        status=status, traffic_pct=max(0, min(100, int(traffic_pct or 0))),
        note=note or "",
    )
    db.add(rec)
    if commit:
        db.commit()
    return rec


def list_versions(db: Session, mode: str) -> list[dict]:
    rows = (
        db.query(TripModeConfigVersion)
        .filter(TripModeConfigVersion.mode == mode)
        .order_by(TripModeConfigVersion.version.desc(), TripModeConfigVersion.id.desc())
        .all()
    )
    return [dict(
        id=r.id, mode=r.mode, version=r.version, status=r.status,
        traffic_pct=r.traffic_pct, note=r.note or "",
        weights=r.weights or {}, hard_rules=r.hard_rules or {},
        description=r.description or "",
        created_at=r.created_at.isoformat(timespec="seconds") if r.created_at else "",
    ) for r in rows]


def rollback(db: Session, mode: str, version: int) -> dict:
    """回滚到指定历史版本：先把当前配置留档，再覆盖并升版本号。"""
    cfg = db.query(TripModeConfig).filter(TripModeConfig.mode == mode).first()
    if cfg is None:
        raise HTTPException(404, "模式不存在")
    rec = (
        db.query(TripModeConfigVersion)
        .filter(TripModeConfigVersion.mode == mode, TripModeConfigVersion.version == version)
        .order_by(TripModeConfigVersion.id.desc())
        .first()
    )
    if rec is None:
        raise HTTPException(404, f"版本不存在: v{version}")

    snapshot(db, cfg, status="history", note=f"回滚到 v{version} 前快照")
    cfg.weights = dict(rec.weights or {})
    cfg.hard_rules = dict(rec.hard_rules or {})
    cfg.slot_template = list(rec.slot_template or [])
    if rec.description:
        cfg.description = rec.description
    cfg.version = _next_version(db, mode, cfg)
    snapshot(db, cfg, status="active", commit=False, note=f"回滚自 v{version}")
    db.commit()
    mode_cache.invalidate_prefix("mode:")
    return dict(mode=mode, version=cfg.version, rolled_back_to=version, message="已回滚并生效")


def create_candidate(
    db: Session, mode: str, weights: dict, hard_rules: dict | None,
    description: str | None, slot_template: list | None, traffic_pct: int, note: str = "",
) -> dict:
    """创建灰度候选版本（不直接改线上配置）。"""
    cfg = db.query(TripModeConfig).filter(TripModeConfig.mode == mode).first()
    if cfg is None:
        raise HTTPException(404, "模式不存在")
    validate_weights(weights)
    version = _next_version(db, mode, cfg)
    rec = TripModeConfigVersion(
        mode=mode, version=version,
        weights=dict(weights or {}),
        hard_rules=dict(hard_rules if hard_rules is not None else (cfg.hard_rules or {})),
        slot_template=list(slot_template if slot_template is not None else (cfg.slot_template or [])),
        description=description if description is not None else (cfg.description or ""),
        status="candidate", traffic_pct=max(1, min(100, int(traffic_pct or 0))),
        note=note or "灰度候选",
    )
    db.add(rec)
    db.commit()
    return dict(mode=mode, version=version, traffic_pct=rec.traffic_pct,
                status=rec.status, message="灰度候选已创建")


def promote_candidate(db: Session, mode: str, version: int) -> dict:
    """把候选版本转为正式版本（灰度 100%）。"""
    cfg = db.query(TripModeConfig).filter(TripModeConfig.mode == mode).first()
    if cfg is None:
        raise HTTPException(404, "模式不存在")
    rec = (
        db.query(TripModeConfigVersion)
        .filter(
            TripModeConfigVersion.mode == mode,
            TripModeConfigVersion.version == version,
            TripModeConfigVersion.status == "candidate",
        )
        .order_by(TripModeConfigVersion.id.desc())
        .first()
    )
    if rec is None:
        raise HTTPException(404, f"灰度候选不存在: v{version}")

    snapshot(db, cfg, status="history", note=f"全量发布 v{version} 前快照")
    cfg.weights = dict(rec.weights or {})
    cfg.hard_rules = dict(rec.hard_rules or {})
    cfg.slot_template = list(rec.slot_template or [])
    cfg.description = rec.description or cfg.description
    cfg.version = rec.version
    rec.status = "active"
    rec.traffic_pct = 100
    # 其余候选保留，但不再参与灰度
    db.query(TripModeConfigVersion).filter(
        TripModeConfigVersion.mode == mode,
        TripModeConfigVersion.status == "candidate",
        TripModeConfigVersion.id != rec.id,
    ).update({"status": "history"}, synchronize_session=False)
    db.commit()
    mode_cache.invalidate_prefix("mode:")
    return dict(mode=mode, version=cfg.version, message="灰度候选已全量发布")


def delete_candidate(db: Session, mode: str, version: int) -> bool:
    rec = (
        db.query(TripModeConfigVersion)
        .filter(
            TripModeConfigVersion.mode == mode,
            TripModeConfigVersion.version == version,
            TripModeConfigVersion.status == "candidate",
        )
        .first()
    )
    if rec is None:
        return False
    db.delete(rec)
    db.commit()
    return True


def effective_weights(
    db: Session, mode: str, base_weights: dict, key: int | str | None = None,
) -> tuple[dict, dict | None]:
    """按灰度分桶返回权重：命中候选则返回候选权重，否则用当前配置。

    返回 (weights, candidate_meta|None)，便于在响应里标注灰度命中。
    """
    candidates = (
        db.query(TripModeConfigVersion)
        .filter(
            TripModeConfigVersion.mode == mode,
            TripModeConfigVersion.status == "candidate",
            TripModeConfigVersion.traffic_pct > 0,
        )
        .order_by(TripModeConfigVersion.version.desc())
        .all()
    )
    if not candidates:
        return dict(base_weights), None
    bucket_seed = f"{mode}:{key if key is not None else 0}"
    bucket = int(hashlib.md5(bucket_seed.encode("utf-8")).hexdigest(), 16) % 100
    for cand in candidates:
        if bucket < int(cand.traffic_pct or 0):
            return dict(cand.weights or base_weights), dict(
                version=cand.version, traffic_pct=cand.traffic_pct,
            )
    return dict(base_weights), None
