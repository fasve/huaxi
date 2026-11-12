"""预设主题路线：建表补列 + 贵州大学校园游学线种子数据（G7 / T9 / 11.4）。

设计原则：
- 启动时幂等执行，不需要人工跑迁移脚本；重跑 init_db 清空库后会自动补种。
- 线路、逐站讲解、任务卡、date_gate 全部数据化，A7 后台可周更校验政策，不改代码。
- 坐标 / 校园通行时段为**演示近似口径**，已在 sources 中标注 ⚠️ 上线前须与校方核准。
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app.models import (
    Poi, PoiExtStudy, PoiTag, PresetRoute, PresetRouteStop, Tag,
)


# ---------------------------------------------------------------------------
# 游学点 POI（category=study；装箱时按 scenic 入池，见方案 3.2）
# ---------------------------------------------------------------------------
GZU_STUDY_POIS: list[dict] = [
    dict(
        name="贵州大学西校区·明德广场", sub_type="校园广场",
        address="花溪区贵州大学西校区主门内", lon=106.6580, lat=26.4170,
        duration=20, rating=4.6, reviews=3200,
        open=[["08:00", "18:00"]],
        tags=[("campus", 1.0), ("heritage", 0.5), ("photospot", 0.6), ("budget_free", 1.0)],
        ext=dict(org="贵州大学西校区", reservation_channel="iGZU 服务号 → 一校通 → 访客预约",
                 visit_policy="校外行人（含个人与团体）须提前预约，审核后刷身份证或预约码进校；校内禁止骑行、共享单车禁入、无人机禁带。",
                 season_window="", study_theme="校园规划与校史入门"),
    ),
    dict(
        name="贵州大学图书馆·阅湖", sub_type="校园建筑",
        address="花溪区贵州大学西校区阅湖畔", lon=106.6592, lat=26.4180,
        duration=40, rating=4.8, reviews=5100,
        open=[["08:00", "22:00"]],
        tags=[("campus", 1.0), ("photospot", 1.0), ("heritage", 0.6), ("budget_free", 1.0)],
        ext=dict(org="贵州大学西校区", reservation_channel="外观常开；进馆仅限开放时段，需本校预约",
                 visit_policy="图书馆外观全天可参观；入内须遵守校内开放时段与读者管理规定。",
                 season_window="", study_theme="建筑美学与喀斯特校园水循环"),
    ),
    dict(
        name="致诚北路樱花大道", sub_type="季节景观",
        address="花溪区贵州大学西校区致诚北路（体育馆—五食堂段）", lon=106.6605, lat=26.4190,
        duration=40, rating=4.8, reviews=9200,
        open=[["08:00", "18:00"]],
        tags=[("campus", 1.0), ("seasonal", 1.0), ("photospot", 1.0), ("budget_free", 1.0)],
        ext=dict(org="贵州大学西校区", reservation_channel="随校园入校预约",
                 visit_policy="花期约 3 月中旬—4 月初；错季自动替换为贤正湖畔常绿绿道。",
                 season_window="03-15~04-05", study_theme="植物物候观察与花期构图"),
    ),
    dict(
        name="贵州大学校史馆（档案馆）", sub_type="校史展馆",
        address="花溪区贵州大学西校区档案馆", lon=106.6618, lat=26.4175,
        duration=60, rating=4.7, reviews=1800,
        open=[["08:30", "11:30"], ["14:30", "17:00"]],
        tags=[("campus", 1.0), ("heritage", 1.0), ("family", 0.6), ("budget_free", 1.0)],
        ext=dict(org="贵州大学档案馆", reservation_channel="iGZU 服务号访客预约 + 校史馆团体讲解预约",
                 visit_policy="工作日 8:30–11:30 / 14:30–17:00 开放；周末、法定节假日及寒暑假闭馆。",
                 season_window="", study_theme="1902 贵州大学堂以来的校史沿革"),
    ),
    dict(
        name="松林坡·贤正楼红墙段", sub_type="文保建筑",
        address="花溪区贵州大学西校区松林坡", lon=106.6628, lat=26.4162,
        duration=30, rating=4.6, reviews=1400,
        open=[["08:00", "18:00"]],
        tags=[("campus", 1.0), ("heritage", 0.9), ("photospot", 0.7), ("budget_free", 1.0)],
        ext=dict(org="贵州大学西校区", reservation_channel="随校园入校预约",
                 visit_policy="苏式红砖灰瓦建筑群，仅外观参观，禁止攀爬进入。",
                 season_window="", study_theme="近现代建筑测绘与抗战办学史"),
    ),
    dict(
        name="贤正湖畔常绿绿道", sub_type="常绿景观",
        address="花溪区贵州大学西校区贤正湖畔", lon=106.6598, lat=26.4198,
        duration=40, rating=4.5, reviews=900,
        open=[["07:00", "20:00"]],
        tags=[("campus", 1.0), ("nature", 0.8), ("budget_free", 1.0)],
        ext=dict(org="贵州大学西校区", reservation_channel="随校园入校预约",
                 visit_policy="全年常绿，作为樱花大道非花期替换站。",
                 season_window="", study_theme="常绿树种辨识与校园生态"),
    ),
    dict(
        name="西校区校门·花溪公园站衔接", sub_type="出校动线",
        address="花溪区贵州大学西校区主门（地铁 3 号线花溪公园站方向）", lon=106.6570, lat=26.4165,
        duration=30, rating=4.4, reviews=600,
        open=[["08:00", "18:00"]],
        tags=[("campus", 1.0), ("budget_free", 1.0)],
        ext=dict(org="贵州大学西校区", reservation_channel="随校园入校预约",
                 visit_policy="归还动线：步行或地铁 3 号线花溪公园站方向，衔接花溪公园、十里河滩等自由游资源。",
                 season_window="", study_theme="游学总结与自由游衔接"),
    ),
    dict(
        name="贵州大学南校区近现代建筑群", sub_type="省级文保",
        address="花溪区贵州大学南校区", lon=106.6700, lat=26.4080,
        duration=90, rating=4.7, reviews=2100,
        open=[["09:00", "17:00"]],
        tags=[("campus", 1.0), ("heritage", 1.0), ("photospot", 0.7), ("budget_free", 1.0)],
        ext=dict(org="贵州大学南校区", reservation_channel="随校园入校预约；文保点仅外观参观",
                 visit_policy="2021 年 6 月获批省级文物保护单位：校长办公楼(1941)、同心楼(1953)、同德楼(1956)、老图书馆·同文楼(1953)；仅外观参观，任务卡禁止攀爬进入。",
                 season_window="", study_theme="建筑遗产测绘与家国记忆"),
    ),
]


# ---------------------------------------------------------------------------
# 线路元信息
# ---------------------------------------------------------------------------
GZU_ROUTE: dict = dict(
    code="gzu_campus_study_tour",
    title="百年贵大 · 溪山校园游学线",
    subtitle="建筑遗产 + 校史 + 生态辨识三合一的半日研学动线",
    theme="study_tour",
    target_group="亲子研学 / 中学生访校 / 人文游客",
    duration_hours=4.0,
    season_window={"start": "03-15", "end": "04-05", "label": "樱花花期"},
    difficulty="轻松（全程步行约 3.5km）",
    enabled=True,
    version=1,
    summary=(
        "从西校区主门明德广场出发，沿中国红「回转印章」图书馆与阅湖水禽、"
        "春季樱花大道、百年校史馆、松林坡苏式红砖建筑群，"
        "把校园规划、建筑遗产、校史沿革与喀斯特校园生态串成一条可讲、可拍、可做题的半日游学线。"
        "全程步行（校内禁止骑行与共享单车入内），站点间衔接时长按校内实测预置，不走外部路径规划 API。"
    ),
    cover_image="",
    reservation_note=(
        "校外行人（含个人、团体）均需预约：经「iGZU」微信服务号 →「一校通」→「访客预约」"
        "提交姓名 / 证件 / 事由，审核后刷身份证或预约码进校；本校教职工可代为邀约。"
    ),
    transit_note=(
        "校园通行参考时段：工作日 8:00–17:30，周末 / 节假日 9:00–17:00 ⚠️ 单源攻略口径，"
        "上线前须与学校保卫部门核实。出校后可步行 / 地铁 3 号线花溪公园站方向衔接花溪其余资源，"
        "使用「一键成程」即可拼出半天游学 + 半天自由游。"
    ),
    mode_tips={
        "leisure": "保留全部 6 站但压缩为 3.5h，阅湖草坪增加 30min 休憩槽",
        "blitz": "半日线 + 下午花溪公园 / 十里河滩串线，樱花季优先调度",
        "premium": "不排樱花高峰周末，校史馆预约讲解团 + 校外悦读时光咖啡馆（北校区中山园）作休憩点",
        "checkin": "樱花大道 + 图书馆印章楼 + 明德广场三点出片动线，日落时段置后",
    },
    sources=[
        dict(item="入校预约机制（iGZU 访客预约、刷身份证 / 二维码通行）", source="贵州大学官方知识库口径", verified=True),
        dict(item="校史馆开放时段（工作日 8:30–11:30 / 14:30–17:00，周末节假日寒暑假闭馆）", source="贵州大学档案馆官网 ar.gzu.edu.cn", verified=True),
        dict(item="南校区近现代建筑群 2021 年 6 月获批省级文保及各楼年代", source="贵大文明网 / 校友总会 / 中国大学生在线", verified=True),
        dict(item="樱花大道位置（西校区致诚北路）与花期（3 月中旬—4 月初）", source="贵大新闻网 / 官方公众号", verified=True),
        dict(item="校园通行开放时段（工作日 8:00–17:30、周末 9:00–17:00）", source="第三方参观攻略 ⚠️ 单源待校验", verified=False,
             note="上线前必须与校方保卫部门正面核实；政策变动由 A7 后台周更校验同步"),
        dict(item="校园内各站点坐标", source="演示近似值 ⚠️ 待核准", verified=False,
             note="仅用于分布示意，接入真实业务数据须统一到 GCJ-02"),
    ],
    policy_checked_at="2026-11-11",
)


# ---------------------------------------------------------------------------
# 站点序列（方案 11.4 半日精华版 6 站 + 全天深度版加段）
# date_gate 的 fallback_poi_id 在 seed 时按 POI 名称回填
# ---------------------------------------------------------------------------
RESERVATION_GATE = dict(
    type="reservation_required",
    channel="iGZU 微信服务号 → 一校通 → 访客预约",
    lead_days=1,
    note="校外行人须提前预约，审核后刷身份证或预约码进校",
    task="出行前 1 天完成访客预约，全员携带身份证 / 预约码",
)

GZU_STOPS: list[dict] = [
    dict(
        seq=1, poi_name="贵州大学西校区·明德广场", stay_min=20, walk_in_min=0,
        slot="morning", must_visit=True,
        narration_title="校园规划轴线与入学庆典",
        narration_text=(
            "从主门沿中轴线步入明德广场，先看清校园的「一条轴线、两翼展开」格局："
            "广场喷泉与两侧教学楼构成入学庆典、开学典礼的核心场景。"
            "这里也是理解贵大「溪山校园」山水格局的最佳起点。"
        ),
        task_card=dict(title="校徽寻宝", type="观察",
                      content="找到校徽上的元素（1902、溪山、书本）并在广场拍一张合影"),
        photo_tip="以喷泉为中轴、图书馆红建筑为背景的对称构图",
        date_gate=[RESERVATION_GATE],
        degrade_text="",
    ),
    dict(
        seq=2, poi_name="贵州大学图书馆·阅湖", stay_min=40, walk_in_min=8,
        slot="morning", must_visit=True,
        narration_title="中国红「回转印章」与喀斯特水循环",
        narration_text=(
            "图书馆取中国红与「回转印章」造型，是西校区的视觉地标；"
            "湖畔常见黑天鹅等水禽，可顺带讲喀斯特地区地表水—地下水循环与校园雨水花园设计。"
            "外观全天可看，进馆仅限开放时段。"
        ),
        task_card=dict(title="水禽行为记录", type="记录",
                      content="安静观察 5 分钟，记录 2 种水禽的行为（觅食 / 理羽 / 游弋）"),
        photo_tip="湖面倒影 + 印章楼转角，上午侧光最佳",
        date_gate=[dict(type="open_hours", windows=[["08:00", "22:00"]], note="外观常开；进馆仅限开放时段")],
        degrade_text="",
    ),
    dict(
        seq=3, poi_name="致诚北路樱花大道", stay_min=40, walk_in_min=10,
        slot="morning", must_visit=True,
        narration_title="近千株樱花春季花廊",
        narration_text=(
            "致诚北路体育馆—五食堂段春季形成近千米樱花花廊，也是民族文化快闪的举办地。"
            "可讲物候期（初花 / 盛花 / 落花）与樱花对温度累积的响应。"
        ),
        task_card=dict(title="花期构图", type="拍摄",
                      content="拍一张樱花与图书馆玻璃幕墙同框的照片，注意前景虚化"),
        photo_tip="低机位仰拍，用花枝做前景框住红建筑",
        date_gate=[dict(
            type="season_window", start="03-15", end="04-05",
            fallback_name="贤正湖畔常绿绿道", name="樱花大道",
            task="改做常绿树种辨识",
        )],
        degrade_text=(
            "当前非樱花花期，本站改为贤正湖畔常绿绿道：辨识香樟、桂花等常绿树种，"
            "观察喀斯特校园水循环，同样能完成生态观察任务。"
        ),
        fallback_poi_name="贤正湖畔常绿绿道",
    ),
    dict(
        seq=4, poi_name="贵州大学校史馆（档案馆）", stay_min=60, walk_in_min=15,
        slot="afternoon", must_visit=True,
        narration_title="1902 → 1951 → 211 / 双一流",
        narration_text=(
            "从 1902 年贵州大学堂，到 1951 年毛泽东题写校名，再到并校、211 与双一流，"
            "馆内以实物档案串起一条清晰的时间线，是整条线路知识密度最高的一站。"
        ),
        task_card=dict(title="校史时间线填空", type="思辨",
                      content="把 1902 / 1951 / 1997 / 2004 四个并校与更名年份按先后排序，并说出各自事件"),
        photo_tip="馆外校史展板与时间线墙",
        date_gate=[
            dict(type="weekday_only", name="校史馆", lead_days=0),
            dict(type="open_hours", windows=[["08:30", "11:30"], ["14:30", "17:00"]],
                 note="周末、法定节假日及寒暑假闭馆"),
        ],
        degrade_text=(
            "校史馆今日不开放，改为广场校史展板的馆外讲解："
            "按 1902 贵州大学堂 → 1951 题写校名 → 并校 → 双一流 的顺序完成时间线任务，"
            "不进入室内，停留压缩至 20 分钟。"
        ),
        degrade_stay_min=20,
    ),
    dict(
        seq=5, poi_name="松林坡·贤正楼红墙段", stay_min=30, walk_in_min=12,
        slot="afternoon", must_visit=True,
        narration_title="苏式红砖灰瓦与抗战办学往事",
        narration_text=(
            "松林坡一带保留苏式红砖灰瓦建筑群落，连排拱窗、坡顶与厚墙是 1950 年代校园建筑的典型语汇，"
            "也关联抗战时期西南办学的历史记忆。本区仅外观参观。"
        ),
        task_card=dict(title="建筑速写", type="动手",
                      content="数出一段立面的连排拱窗数量，画一张包含坡顶与拱窗的建筑速写"),
        photo_tip="红墙长廊的透视构图，午后斜光更立体",
        date_gate=[dict(type="reservation_required", channel="随校园入校预约",
                        lead_days=1, task="文保建筑仅外观参观，禁止攀爬进入")],
        degrade_text="",
    ),
    dict(
        seq=6, poi_name="西校区校门·花溪公园站衔接", stay_min=30, walk_in_min=10,
        slot="afternoon", must_visit=False,
        narration_title="出校动线与自由游衔接",
        narration_text=(
            "沿贤正湖绿道收尾，步行约 10 分钟回到校门方向。"
            "此站为弹性站：时间充裕时完成生态观察；赶时间可直接出校，"
            "用「一键成程」把下午交给花溪公园 / 十里河滩 / 青岩古镇等自由游资源。"
        ),
        task_card=dict(title="校园生态小结", type="总结",
                      content="用 3 句话总结今天观察到的建筑、校史与生态各一个知识点"),
        photo_tip="湖畔绿道尽头回望红建筑群",
        date_gate=[],
        degrade_text="",
    ),
    # ---- 全天深度版加段（is_addon）：半日线后接南校区文保建筑群 ----
    dict(
        seq=7, poi_name="贵州大学南校区近现代建筑群", stay_min=90, walk_in_min=25,
        slot="afternoon", must_visit=False, is_addon=True,
        narration_title="建筑遗产测绘 + 家国记忆",
        narration_text=(
            "公交 / 步行至南校区（2021 年 6 月获批省级文物保护单位）："
            "校长办公楼（1941，国立贵州大学首任校长办公地）→ 同心楼（1953）→ 同德楼（1956）"
            "→ 老图书馆·同文楼（1953，砖木二层红瓦坡顶）→ 抗战林与七女坟（爱国主义纪念点），"
            "最后经学士路梧桐林荫道收尾。文保点仅外观参观。"
        ),
        task_card=dict(title="年代测绘卡", type="动手",
                      content="为 4 栋建筑标注建成年份，比较砖木结构与苏式红砖的立面差异；禁止攀爬进入"),
        photo_tip="同文楼红瓦坡顶与梧桐林荫道",
        date_gate=[dict(type="reservation_required", channel="随校园入校预约",
                        lead_days=1, task="文保点仅外观参观，任务卡禁止攀爬进入")],
        degrade_text="",
    ),
]


TRIP_ALTER_COLUMNS = [
    ("preset_route_code", "VARCHAR(64) NULL COMMENT '预设主题路线 code；空=普通模式行程'"),
    ("visit_date", "VARCHAR(10) NULL COMMENT '出行日期 YYYY-MM-DD；date_gate 判定依据'"),
]


def ensure_schema() -> list[str]:
    """幂等：建 preset_route / preset_route_stop 表，并为 trip 补两列。

    服务启动时调用，避免「改了 models 但线上库缺列」导致 SELECT 报错。
    """
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    existing = {c["name"] for c in insp.get_columns("trip")} if "trip" in insp.get_table_names() else set()
    added: list[str] = []
    for name, ddl in TRIP_ALTER_COLUMNS:
        if name in existing:
            continue
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE trip ADD COLUMN {name} {ddl}"))
        added.append(name)
    return added


def _upsert_study_pois(db: Session) -> dict[str, int]:
    """按名称幂等写入 study POI + 扩展表 + 标签，返回 名称→id 映射。"""
    tag_map = {t.code: t.id for t in db.query(Tag).all()}
    name_to_id: dict[str, int] = {}
    for item in GZU_STUDY_POIS:
        p = db.query(Poi).filter(Poi.name == item["name"]).first()
        if p is None:
            p = Poi(
                name=item["name"], category="study", sub_type=item["sub_type"],
                address=item["address"], longitude=item["lon"], latitude=item["lat"],
                district="花溪区", open_time=item["open"],
                suggest_duration_min=item["duration"], ticket_price=0, price_level=1,
                rating=item["rating"], review_count=item["reviews"],
                hot_score=0.55, quality_score=0.85, visitable=True,
                images=[], image_meta=[],
            )
            db.add(p)
            db.flush()
        name_to_id[item["name"]] = p.id

        ext = item["ext"]
        if db.get(PoiExtStudy, p.id) is None:
            db.add(PoiExtStudy(
                poi_id=p.id, org=ext.get("org", ""),
                reservation_channel=ext.get("reservation_channel", ""),
                visit_policy=ext.get("visit_policy", ""),
                season_window=ext.get("season_window", ""),
                study_theme=ext.get("study_theme", ""),
            ))
        for code, weight in item["tags"]:
            if code not in tag_map:
                continue
            exists = db.query(PoiTag).filter(
                PoiTag.poi_id == p.id, PoiTag.tag_id == tag_map[code]
            ).first()
            if exists is None:
                db.add(PoiTag(poi_id=p.id, tag_id=tag_map[code], weight=weight))
    db.flush()
    return name_to_id


def seed_if_empty(force: bool = False) -> dict:
    """幂等写入贵大校园游学线；force=True 会重建线路（保留 study POI）。"""
    db = SessionLocal()
    try:
        route = db.query(PresetRoute).filter(
            PresetRoute.code == GZU_ROUTE["code"]
        ).first()
        if route is not None and not force:
            return dict(action="skipped", code=route.code,
                        stops=db.query(PresetRouteStop).filter(
                            PresetRouteStop.route_id == route.id).count())

        name_to_id = _upsert_study_pois(db)
        if route is not None:
            db.query(PresetRouteStop).filter(
                PresetRouteStop.route_id == route.id
            ).delete(synchronize_session=False)
            db.delete(route)
            db.flush()

        meta = {k: v for k, v in GZU_ROUTE.items()}
        route = PresetRoute(**meta)
        db.add(route)
        db.flush()

        count = 0
        for st in GZU_STOPS:
            poi_id = name_to_id.get(st["poi_name"])
            if poi_id is None:
                continue
            gates = [dict(g) for g in st.get("date_gate", [])]
            fb_name = st.get("fallback_poi_name")
            fb_id = name_to_id.get(fb_name) if fb_name else None
            for g in gates:
                if g.get("type") == "season_window" and fb_id:
                    g["fallback_poi_id"] = fb_id
            db.add(PresetRouteStop(
                route_id=route.id, seq=st["seq"], poi_id=poi_id,
                stay_min=st["stay_min"], walk_in_min=st["walk_in_min"],
                narration_title=st["narration_title"],
                narration_text=st["narration_text"],
                task_card=st["task_card"], photo_tip=st["photo_tip"],
                must_visit=st["must_visit"],
                date_gate=gates,
                fallback_poi_id=fb_id,
                degrade_text=st.get("degrade_text", ""),
                degrade_stay_min=st.get("degrade_stay_min", 0),
                slot=st.get("slot", "morning"),
                is_addon=st.get("is_addon", False),
            ))
            count += 1
        db.commit()
        return dict(action="seeded" if not force else "reseeded",
                    code=route.code, stops=count, pois=len(name_to_id))
    finally:
        db.close()


def ensure_preset_routes() -> dict:
    """启动时的一步到位入口：补列 → 建表 → 补种子。"""
    added = ensure_schema()
    result = seed_if_empty()
    result["trip_columns_added"] = added
    return result
