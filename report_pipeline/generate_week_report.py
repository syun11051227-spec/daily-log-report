#!/usr/bin/env python3
"""
週次レポートを HTML として書き出す（実行日＝今日、Asia/Shanghai の週境界）。

環境変数:
  GOOGLE_SHEETS_SPREADSHEET_ID … 必須
  GOOGLE_SERVICE_ACCOUNT_JSON … 任意。設定時はサービスアカウントで読み取り（GitHub Actions 向け）
  GOOGLE_APPLICATION_CREDENTIALS … 任意。サービスアカウント JSON ファイルのパス

例:
  python generate_week_report.py -o ../dist/week_report.html
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from coach_comments import build_coach_cards
from daily_log import load_daily_log
from week_aggregate import STUDY_HEX, STUDY_ITEMS_ORDER, build_week_report, svg_weight_polyline


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

    coach_cards = build_coach_cards(rep)

    env = Environment(
        loader=FileSystemLoader(str(_base_dir() / "templates")),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tpl = env.get_template("week_report.html.j2")
    html = tpl.render(
        rep=rep,
        study_cols=study_cols,
        goal_line_bottom_pct=goal_line_bottom_pct,
        weight_polyline=poly,
        weight_polygon_fill=poly_fill,
        weight_circles=circles,
        weight_goal_y=goal_y,
        run_bars=run_bars,
        run_goal_bottom_pct=run_goal_bottom_pct,
        coach_cards=coach_cards,
    )
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
