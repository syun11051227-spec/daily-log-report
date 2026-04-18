"""週次レポート用の集計（仕様はプロジェクト内の合意に基づく）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import pandas as pd

TZ = ZoneInfo("Asia/Shanghai")

TRACKED_CATEGORIES = ("学習", "運動", "健康")
STUDY_ITEMS_ORDER = ("Duolingo", "中国語", "プログラミング", "ドリル")
# Tailwind の study-* と同色（JIT が動的 class 名を落とさないよう HTML では hex を使う）
STUDY_HEX = ("#0a84ff", "#30b0c7", "#ff9500", "#636366")

GOAL_STUDY_MIN_PER_DAY = 60
GOAL_WEIGHT_KG = 68.0
GOAL_RUN_KM_PER_DAY = 5.0
GOAL_PACE_MIN_PER_KM = 6.0  # 6:00/km

DayKind = Literal["full", "partial", "empty"]


def today_in_tz() -> date:
    """Asia/Shanghai の暦日（推奨）。"""
    from datetime import datetime

    return datetime.now(TZ).date()


def monday_week(d: date) -> tuple[date, date]:
    monday = d - timedelta(days=d.weekday())
    return monday, monday + timedelta(days=6)


def minutes_from_row(unit: str, value: float) -> float:
    u = str(unit).strip()
    if u == "分":
        return float(value)
    if u == "時間":
        return float(value) * 60.0
    return 0.0


def parse_pace_min_per_km(note: str) -> float | None:
    s = str(note).strip()
    if not s or ":" not in s:
        return None
    parts = s.split(":")
    if len(parts) != 2:
        return None
    try:
        m = int(parts[0].strip())
        sec = int(parts[1].strip())
    except ValueError:
        return None
    return m + sec / 60.0


def add_normalized_minutes_column(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    mins: list[float] = []
    for _, r in out.iterrows():
        if str(r.get("category", "")).strip() != "学習":
            mins.append(0.0)
            continue
        u = str(r.get("unit", "")).strip()
        v = r.get("value")
        if pd.isna(v):
            mins.append(0.0)
        else:
            mins.append(minutes_from_row(u, float(v)))
    out["_study_min"] = mins
    return out


def day_kind_for_tracked(df_day: pd.DataFrame) -> tuple[DayKind, int]:
    """学習・運動・健康のみでフル／部分／未を判定。星数は該当カテゴリ数（1〜2は部分）。"""
    if df_day.empty:
        return "empty", 0
    cats = {str(c).strip() for c in df_day["category"] if pd.notna(c)}
    hit = [c for c in TRACKED_CATEGORIES if c in cats]
    n = len(hit)
    if n == 3:
        return "full", 3
    if n >= 1:
        return "partial", n
    return "empty", 0


def any_input_on_day(df: pd.DataFrame, d: date) -> bool:
    day = df[df["date"].dt.date == d]
    return not day.empty


def streak_any_input_days(df: pd.DataFrame, end: date) -> int:
    """end から遡り、いずれか1行でもある日を連続カウント。"""
    d = end
    n = 0
    while any_input_on_day(df, d):
        n += 1
        d -= timedelta(days=1)
    return n


def full_days_in_range(df: pd.DataFrame, start: date, end: date) -> int:
    n = 0
    d = start
    while d <= end:
        sub = df[df["date"].dt.date == d]
        kind, _ = day_kind_for_tracked(sub)
        if kind == "full":
            n += 1
        d += timedelta(days=1)
    return n


def week_rate_percent(full_days: int) -> int:
    return int(round(100.0 * full_days / 7.0))


@dataclass
class DayTile:
    weekday_label: str  # 月…日
    kind: DayKind
    stars: int
    aria: str


@dataclass
class WeekReport:
    week_start: date
    week_end: date
    label_range: str
    prev_full_days: int
    prev_rate: int
    tiles: list[DayTile]
    streak_any_input: int
    week_full_days: int
    month_full_days: int
    month_days_total: int
    week_rate: int
    study_by_day: list[dict[str, float]]  # 7 entries, keys item -> minutes
    study_max_day_min: float
    weight_series: list[float | None]  # 7 aligned, forward-filled for chart
    weight_labels: tuple[str | None, str | None]
    run_km_by_day: list[float]
    run_max_km: float
    pace_avg_min_per_km: str | None
    pace_goal_label: str


def prepare_df(df: pd.DataFrame) -> pd.DataFrame:
    d = df.dropna(subset=["date"]).copy()
    s = pd.to_datetime(d["date"], errors="coerce")
    if pd.api.types.is_datetime64tz_dtype(s.dtype):
        s = s.dt.tz_convert(TZ).dt.tz_localize(None)
    d["date"] = s.dt.normalize()
    return add_normalized_minutes_column(d)


def build_week_report(df: pd.DataFrame, as_of: date | None = None) -> WeekReport:
    as_of = as_of if as_of is not None else today_in_tz()
    df = prepare_df(df)
    mon, sun = monday_week(as_of)
    prev_mon, _prev_sun = monday_week(mon - timedelta(days=1))

    wd_labels = ["月", "火", "水", "木", "金", "土", "日"]
    tiles: list[DayTile] = []
    study_by_day: list[dict[str, float]] = []
    run_km_by_day: list[float] = []

    for i in range(7):
        d = mon + timedelta(days=i)
        sub = df[df["date"].dt.date == d]
        kind, stars = day_kind_for_tracked(sub)
        if kind == "full":
            aria = f"{wd_labels[i]}曜 フル達成"
        elif kind == "partial":
            aria = f"{wd_labels[i]}曜 部分達成（{stars}カテゴリ）"
        else:
            aria = f"{wd_labels[i]}曜 未入力"
        tiles.append(DayTile(weekday_label=wd_labels[i], kind=kind, stars=stars, aria=aria))

        study = sub[sub["category"].astype(str).str.strip() == "学習"]
        per_item: dict[str, float] = {k: 0.0 for k in STUDY_ITEMS_ORDER}
        for _, r in study.iterrows():
            it = str(r.get("item", "")).strip()
            if it in per_item:
                per_item[it] += float(r.get("_study_min", 0.0) or 0.0)
        study_by_day.append(per_item)

        run = sub[
            (sub["category"].astype(str).str.strip() == "運動")
            & (sub["item"].astype(str).str.strip() == "ランニング")
            & (sub["unit"].astype(str).str.strip() == "km")
        ]
        km = float(run["value"].fillna(0).sum()) if not run.empty else 0.0
        run_km_by_day.append(km)

    daily_totals = [sum(day.values()) for day in study_by_day]
    study_max_day_min = max(GOAL_STUDY_MIN_PER_DAY, max(daily_totals) if daily_totals else GOAL_STUDY_MIN_PER_DAY)

    # 体重: 当日最終（時刻列はパースしないため行順の最後）。欠測は None。
    raw_w: list[float | None] = []
    for i in range(7):
        d = mon + timedelta(days=i)
        sub = df[df["date"].dt.date == d]
        wsub = sub[
            (sub["item"].astype(str).str.strip() == "体重")
            & (sub["unit"].astype(str).str.strip() == "kg")
        ]
        if wsub.empty:
            raw_w.append(None)
        else:
            last = wsub.iloc[-1]
            raw_w.append(float(last["value"]) if pd.notna(last.get("value")) else None)

    weight_series: list[float | None] = []
    last: float | None = None
    for v in raw_w:
        if v is not None:
            last = v
        weight_series.append(last)

    w_first = next((x for x in weight_series if x is not None), None)
    w_last = next((x for x in reversed(weight_series) if x is not None), None)
    weight_labels = (
        f"{w_first:.1f}" if w_first is not None else None,
        f"{w_last:.1f}" if w_last is not None else None,
    )

    run_max_km = max(GOAL_RUN_KM_PER_DAY, max(run_km_by_day) if run_km_by_day else GOAL_RUN_KM_PER_DAY)

    run_week = df[(df["date"].dt.date >= mon) & (df["date"].dt.date <= sun)]
    run_rows = run_week[
        (run_week["category"].astype(str).str.strip() == "運動")
        & (run_week["item"].astype(str).str.strip() == "ランニング")
        & (run_week["unit"].astype(str).str.strip() == "km")
    ]
    pace_parts: list[tuple[float, float]] = []
    for _, r in run_rows.iterrows():
        km = float(r["value"]) if pd.notna(r.get("value")) else 0.0
        if km <= 0:
            continue
        p = parse_pace_min_per_km(str(r.get("note_pace", "")))
        if p is None:
            continue
        pace_parts.append((p, km))
    pace_avg: str | None = None
    if pace_parts:
        num = sum(p * k for p, k in pace_parts)
        den = sum(k for _, k in pace_parts)
        avg = num / den if den > 0 else None
        if avg is not None:
            whole = int(avg)
            sec = int(round((avg - whole) * 60))
            if sec >= 60:
                whole += 1
                sec -= 60
            pace_avg = f"{whole}:{sec:02d}"

    prev_full = full_days_in_range(df, prev_mon, prev_mon + timedelta(days=6))
    week_full = full_days_in_range(df, mon, sun)

    month_start = date(as_of.year, as_of.month, 1)
    if as_of.month == 12:
        month_end = date(as_of.year, 12, 31)
    else:
        month_end = date(as_of.year, as_of.month + 1, 1) - timedelta(days=1)
    month_full = full_days_in_range(df, month_start, month_end)
    month_total = (month_end - month_start).days + 1

    label_range = f"{mon.month}/{mon.day} — {sun.month}/{sun.day}"

    return WeekReport(
        week_start=mon,
        week_end=sun,
        label_range=label_range,
        prev_full_days=prev_full,
        prev_rate=week_rate_percent(prev_full),
        tiles=tiles,
        streak_any_input=streak_any_input_days(df, as_of),
        week_full_days=week_full,
        month_full_days=month_full,
        month_days_total=month_total,
        week_rate=week_rate_percent(week_full),
        study_by_day=study_by_day,
        study_max_day_min=study_max_day_min,
        weight_series=weight_series,
        weight_labels=weight_labels,
        run_km_by_day=run_km_by_day,
        run_max_km=run_max_km,
        pace_avg_min_per_km=pace_avg,
        pace_goal_label="6:00",
    )


def svg_weight_polyline(weights: list[float | None]) -> tuple[str, str, str, float]:
    """viewBox 0 0 400 150 に合わせた polyline / polygon / goal y。"""
    xs = [20 + i * 60 for i in range(7)]
    vals = [w for w in weights if w is not None]
    if not vals:
        return "", "", "", GOAL_WEIGHT_KG
    w_min = min(vals) - 0.5
    w_max = max(vals) + 0.5
    if w_max - w_min < 0.5:
        w_max = w_min + 0.5
    y_base = 128
    y_top = 40

    def y_for(w: float) -> float:
        t = (w - w_min) / (w_max - w_min)
        return y_base - t * (y_base - y_top)

    pts: list[tuple[float, float]] = []
    for i, w in enumerate(weights):
        if w is None:
            continue
        pts.append((xs[i], y_for(w)))
    if not pts:
        return "", "", "", GOAL_WEIGHT_KG
    poly = " ".join(f"{x:.0f},{y:.1f}" for x, y in pts)
    poly_fill = poly + f" {pts[-1][0]:.0f},{y_base} {pts[0][0]:.0f},{y_base}"
    goal_y = y_for(GOAL_WEIGHT_KG)
    goal_y = max(y_top, min(y_base, goal_y))
    circles = "\n".join(
        f'<circle cx="{x:.0f}" cy="{y:.1f}" r="5" />' for x, y in pts[:1] + pts[-1:]
    ) if len(pts) >= 2 else f'<circle cx="{pts[0][0]:.0f}" cy="{pts[0][1]:.1f}" r="5" />'
    return poly, poly_fill, circles, goal_y
