#!/usr/bin/env python3
"""
週次レポートを HTML として書き出す（実行日＝今日、Asia/Shanghai の週境界。
月曜は「今週」ではなく先週月〜日を表示する）。

環境変数:
  GOOGLE_SHEETS_SPREADSHEET_ID … 必須
  GOOGLE_SERVICE_ACCOUNT_JSON … 任意。設定時はサービスアカウントで読み取り（GitHub Actions 向け）
  GOOGLE_APPLICATION_CREDENTIALS … 任意。サービスアカウント JSON ファイルのパス
  GEMINI_API_KEY または GOOGLE_API_KEY … 任意。設定時はコーチ文を Gemini で生成（失敗時はルールベースにフォールバック）
  GEMINI_MODEL … 任意（既定: gemini-2.5-flash）

例:
  python generate_week_report.py -o ../dist/week_report.html
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from coach_comments import (
    build_coach_cards,
    build_coach_cards_month,
    build_coach_cards_year,
    pick_coach_cards_for_display,
)
from coach_llm_gemini import (
    try_gemini_coach_cards,
    try_gemini_coach_cards_month,
    try_gemini_coach_cards_year,
)
from daily_log import load_daily_log
from week_aggregate import (
    GOAL_RUN_KM_PER_DAY,
    STUDY_HEX,
    STUDY_ITEMS_ORDER,
    build_month_report,
    build_week_report,
    build_year_report,
    svg_weight_polyline,
    svg_weight_polyline_n,
)


def _base_dir() -> Path:
    return Path(__file__).resolve().parent


def main() -> None:
    p = argparse.ArgumentParser(description="週次レポート HTML を生成")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=_base_dir() / "out" / "week_report.html",
        help="出力 HTML パス",
    )
    args = p.parse_args()
    out: Path = args.output
    out.parent.mkdir(parents=True, exist_ok=True)

    df = load_daily_log()
    if df.empty:
        print("DailyLog が空です。", file=sys.stderr)
        sys.exit(1)

    rep = build_week_report(df)
    mrep = build_month_report(df)
    yrep = build_year_report(df)

    # 勉強チャート用: 各日・各項目の高さ%（その日の合計に対する割合 × 列の高さ%）
    study_cols: list[list[tuple[str, float]]] = []
    for day in rep.study_by_day:
        total = sum(day.values())
        col_h = min(100.0, (total / rep.study_max_day_min) * 100.0) if rep.study_max_day_min > 0 else 0.0
        segs = []
        for item, color in zip(STUDY_ITEMS_ORDER, STUDY_HEX):
            if total > 0 and col_h > 0:
                frac = day[item] / total
                h = max(0.0, min(100.0, col_h * frac))
            else:
                h = 0.0
            segs.append((color, h))
        study_cols.append(segs)

    goal_line_bottom_pct = min(
        100.0,
        (60.0 / rep.study_max_day_min) * 100.0 if rep.study_max_day_min > 0 else 0.0,
    )

    poly, poly_fill, circles, goal_y = svg_weight_polyline(rep.weight_series)

    run_bars = [
        min(100.0, (km / rep.run_max_km) * 100.0) if rep.run_max_km > 0 else 0.0
        for km in rep.run_km_by_day
    ]
    run_goal_bottom_pct = min(100.0, (5.0 / rep.run_max_km) * 100.0) if rep.run_max_km > 0 else 0.0

    coach_cards = try_gemini_coach_cards(rep)
    if coach_cards is None:
        coach_cards = pick_coach_cards_for_display(build_coach_cards(rep))

    month_study_cols: list[list[tuple[str, float]]] = []
    for week in mrep.study_by_week:
        total = sum(week.values())
        col_h = (
            min(100.0, (total / mrep.study_max_week_min) * 100.0)
            if mrep.study_max_week_min > 0
            else 0.0
        )
        segs = []
        for item, color in zip(STUDY_ITEMS_ORDER, STUDY_HEX):
            if total > 0 and col_h > 0:
                frac = week[item] / total
                h = max(0.0, min(100.0, col_h * frac))
            else:
                h = 0.0
            segs.append((color, h))
        month_study_cols.append(segs)

    month_goal_line_bottom_pct = min(
        100.0,
        (60.0 * 7.0 / mrep.study_max_week_min) * 100.0 if mrep.study_max_week_min > 0 else 0.0,
    )

    mpoly, mpoly_fill, mcircles, mgoal_y = svg_weight_polyline_n(mrep.weight_series_weeks)

    month_run_bars = [
        min(100.0, (km / mrep.run_max_week_km) * 100.0) if mrep.run_max_week_km > 0 else 0.0
        for km in mrep.run_km_by_week
    ]
    month_run_goal_bottom_pct = min(
        100.0,
        (GOAL_RUN_KM_PER_DAY * 7.0 / mrep.run_max_week_km) * 100.0
        if mrep.run_max_week_km > 0
        else 0.0,
    )

    coach_cards_month = try_gemini_coach_cards_month(mrep)
    if coach_cards_month is None:
        coach_cards_month = pick_coach_cards_for_display(build_coach_cards_month(mrep))

    month_week_tiles = list(
        zip(mrep.week_monday_labels, mrep.week_rates, mrep.week_rate_highlights)
    )
    month_week_cols = max(1, len(month_week_tiles))

    # 年次チャート
    year_study_cols: list[list[tuple[str, float]]] = []
    for month_data in yrep.study_by_month[: yrep.active_months]:
        total = sum(month_data.values())
        col_h = (
            min(100.0, (total / yrep.study_max_month_min) * 100.0)
            if yrep.study_max_month_min > 0
            else 0.0
        )
        segs = []
        for item, color in zip(STUDY_ITEMS_ORDER, STUDY_HEX):
            if total > 0 and col_h > 0:
                frac = month_data[item] / total
                h = max(0.0, min(100.0, col_h * frac))
            else:
                h = 0.0
            segs.append((color, h))
        year_study_cols.append(segs)

    year_goal_line_bottom_pct = min(
        100.0,
        (60.0 * 30.0 / yrep.study_max_month_min) * 100.0
        if yrep.study_max_month_min > 0
        else 0.0,
    )

    ypoly, ypoly_fill, ycircles, ygoal_y = svg_weight_polyline_n(yrep.weight_series_months)

    year_run_bars = [
        min(100.0, (km / yrep.run_max_month_km) * 100.0) if yrep.run_max_month_km > 0 else 0.0
        for km in yrep.run_km_by_month[: yrep.active_months]
    ]
    year_run_goal_bottom_pct = min(
        100.0,
        (GOAL_RUN_KM_PER_DAY * 30.0 / yrep.run_max_month_km) * 100.0
        if yrep.run_max_month_km > 0
        else 0.0,
    )

    coach_cards_year = try_gemini_coach_cards_year(yrep)
    if coach_cards_year is None:
        coach_cards_year = pick_coach_cards_for_display(build_coach_cards_year(yrep))

    year_month_labels = [label for label, _, _ in yrep.month_tiles[: yrep.active_months]]

    env = Environment(
        loader=FileSystemLoader(str(_base_dir() / "templates")),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tpl = env.get_template("week_report.html.j2")
    html = tpl.render(
        rep=rep,
        mrep=mrep,
        yrep=yrep,
        study_cols=study_cols,
        goal_line_bottom_pct=goal_line_bottom_pct,
        weight_polyline=poly,
        weight_polygon_fill=poly_fill,
        weight_circles=circles,
        weight_goal_y=goal_y,
        run_bars=run_bars,
        run_goal_bottom_pct=run_goal_bottom_pct,
        coach_cards=coach_cards,
        month_study_cols=month_study_cols,
        month_goal_line_bottom_pct=month_goal_line_bottom_pct,
        month_weight_polyline=mpoly,
        month_weight_polygon_fill=mpoly_fill,
        month_weight_circles=mcircles,
        month_weight_goal_y=mgoal_y,
        month_run_bars=month_run_bars,
        month_run_goal_bottom_pct=month_run_goal_bottom_pct,
        coach_cards_month=coach_cards_month,
        month_week_tiles=month_week_tiles,
        month_week_cols=month_week_cols,
        year_study_cols=year_study_cols,
        year_goal_line_bottom_pct=year_goal_line_bottom_pct,
        year_weight_polyline=ypoly,
        year_weight_polygon_fill=ypoly_fill,
        year_weight_circles=ycircles,
        year_weight_goal_y=ygoal_y,
        year_run_bars=year_run_bars,
        year_run_goal_bottom_pct=year_run_goal_bottom_pct,
        coach_cards_year=coach_cards_year,
        year_month_labels=year_month_labels,
    )
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
