#!/usr/bin/env python3
"""
筋トレコーチ AI スクリプト

機能:
  1. 週間トレーニングメニューの生成（generate-menu）
  2. 当日トレーニングへのフィードバック生成（generate-feedback）

使用方法:
  # 週間メニューを生成
  python coach_workout.py generate-menu \\
    --workouts workouts.json \\
    --output coach_plan.json

  # フィードバックを生成（生成後に既存 plan JSON へ追記）
  python coach_workout.py generate-feedback \\
    --workouts workouts.json \\
    --plan coach_plan.json \\
    --date 2026-05-01 \\
    --output coach_plan.json

環境変数:
  GEMINI_API_KEY … Google AI Studio の API キー
  GEMINI_MODEL   … 省略時 gemini-2.0-flash
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from typing import Any


def _get_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        sys.exit(
            "❌ 環境変数 GEMINI_API_KEY が未設定です。\n"
            "   export GEMINI_API_KEY='AIza...'"
        )
    return key.strip()


def _gemini_generate(api_key: str, prompt: str) -> str:
    """Gemini REST API を呼び出してテキストを返す。"""
    import urllib.request

    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    payload = json.dumps(
        {"contents": [{"parts": [{"text": prompt}]}]}
    ).encode()

    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())

    return data["candidates"][0]["content"]["parts"][0]["text"]


def _extract_json(text: str) -> dict[str, Any]:
    """テキストから最初の JSON オブジェクトを抽出してパース。"""
    import re

    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("JSON が見つかりませんでした")
    return json.loads(m.group())


def _load_workouts(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _format_workout_summary(workouts: dict[str, Any], n_days: int = 21) -> str:
    """直近 n_days 日分のワークアウトをテキスト化。"""
    today = date.today()
    lines: list[str] = []
    for ds, wo in sorted(workouts.items(), reverse=True):
        d = date.fromisoformat(ds)
        if (today - d).days > n_days:
            continue
        ex_parts = []
        for ex in wo.get("exercises", []):
            sets_str = ", ".join(
                f"{s.get('w', 0) or '自重'}×{s.get('r', 0)}"
                for s in ex.get("sets", [])
            )
            ex_parts.append(f"{ex['name']}({ex['muscle']}): {sets_str}")
        lines.append(f"{ds}: {wo['type']} [{' / '.join(ex_parts)}]")
    return "\n".join(lines) if lines else "記録なし"


# ──────────────────────────────────────────────────────────
#  generate-menu
# ──────────────────────────────────────────────────────────

def generate_menu(workouts: dict[str, Any], api_key: str) -> dict[str, Any]:
    today = date.today()
    monday = _week_monday(today)
    sunday = monday + timedelta(days=6)
    summary = _format_workout_summary(workouts)

    prompt = f"""あなたはプロのフィットネスコーチです。
以下の直近のトレーニング記録を参考に、今週（月曜日:{monday}）の
週間トレーニングメニューをJSON形式で作成してください。

## 直近のトレーニング記録:
{summary}

## 条件:
- 週3〜4日トレーニング（残りは休息）
- 部位のバランスを考慮（押す・引く・脚など）
- 前回実績より少し挑戦的な重量設定
- daysキーに含めない日は休息日として扱う

## 出力フォーマット（JSONのみ。説明文は不要）:
{{
  "weekStart": "{monday}",
  "weekEnd":   "{sunday}",
  "sentDate":  "{today}",
  "coachMessage": "コーチからの今週のメッセージ（日本語・100文字程度）",
  "days": {{
    "YYYY-MM-DD": {{
      "type": "胸・肩・三頭筋",
      "targets": [
        {{ "name": "種目名", "sets": 4, "reps": "8-10", "weight": "80 kg", "note": "任意コメント（省略可）" }}
      ]
    }}
  }},
  "feedbacks": {{}}
}}"""

    print("⏳ Gemini にメニュー生成を依頼中...")
    text = _gemini_generate(api_key, prompt)
    plan = _extract_json(text)

    # バリデーション
    for key in ("weekStart", "weekEnd", "coachMessage", "days"):
        if key not in plan:
            raise ValueError(f"必須キー '{key}' が不足しています")

    return plan


# ──────────────────────────────────────────────────────────
#  generate-feedback
# ──────────────────────────────────────────────────────────

def generate_feedback(
    workouts: dict[str, Any],
    plan: dict[str, Any],
    target_date: str,
    api_key: str,
) -> dict[str, Any]:
    wo = workouts.get(target_date)
    if not wo:
        raise ValueError(f"{target_date} のワークアウト記録が見つかりません")

    day_plan = plan.get("days", {}).get(target_date, {})
    targets_text = ""
    if day_plan.get("targets"):
        targets_text = "\n目標設定:\n" + "\n".join(
            f"  - {t['name']}: {t['sets']}set × {t['reps']} @ {t['weight']}"
            + (f" ({t['note']})" if t.get('note') else "")
            for t in day_plan["targets"]
        )

    actual_text = "\n実績:\n" + "\n".join(
        f"  - {ex['name']}({ex['muscle']}): "
        + ", ".join(
            f"{'自重' if s['w']==0 else f\"{s['w']}kg\"}×{s['r']}{'秒' if ex.get('isSeconds') else '回'}"
            for s in ex["sets"]
        )
        for ex in wo["exercises"]
    )

    duration_text = f"\n所要時間: {wo['duration']}分" if wo.get("duration") else ""
    memo_text = f"\n本人メモ: {wo['memo']}" if wo.get("memo") else ""

    from datetime import datetime
    sent_at = datetime.now().strftime("%-m/%-d %H:%M")

    prompt = f"""あなたはプロのフィットネスコーチです。
以下のトレーニング記録に対して、具体的で励みになるフィードバックを日本語で作成してください。

## 対象日: {target_date}
## 種別: {wo['type']}
{targets_text}
{actual_text}
{duration_text}
{memo_text}

## 出力フォーマット（JSONのみ。説明文は不要）:
{{
  "text": "詳細なフィードバック文（150〜250文字）",
  "rating": 4,
  "points": [
    {{ "type": "positive", "text": "良かった点1" }},
    {{ "type": "positive", "text": "良かった点2" }},
    {{ "type": "improve",  "text": "次回への改善提案" }}
  ],
  "sentAt": "{sent_at}"
}}

ratingは1〜5の整数。pointsは2〜4項目（positive/improveを適切に組み合わせる）。"""

    print(f"⏳ {target_date} のフィードバックを Gemini に依頼中...")
    text = _gemini_generate(api_key, prompt)
    fb = _extract_json(text)

    for key in ("text", "rating", "points"):
        if key not in fb:
            raise ValueError(f"必須キー '{key}' が不足しています")

    return fb


# ──────────────────────────────────────────────────────────
#  CLI
# ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="筋トレコーチ AI スクリプト")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # generate-menu
    p_menu = sub.add_parser("generate-menu", help="週間メニューを生成")
    p_menu.add_argument("--workouts", required=True, metavar="PATH",
                        help="ワークアウトデータ JSON（アプリからエクスポート）")
    p_menu.add_argument("--output", required=True, metavar="PATH",
                        help="出力先 JSON ファイル")

    # generate-feedback
    p_fb = sub.add_parser("generate-feedback", help="当日フィードバックを生成")
    p_fb.add_argument("--workouts", required=True, metavar="PATH")
    p_fb.add_argument("--plan",     required=True, metavar="PATH",
                      help="既存の週間プラン JSON（出力先と同じファイルでも可）")
    p_fb.add_argument("--date",     required=True, metavar="YYYY-MM-DD",
                      help="対象日")
    p_fb.add_argument("--output",   required=True, metavar="PATH",
                      help="更新後の週間プラン JSON の出力先")

    args = parser.parse_args()
    api_key = _get_api_key()

    if args.cmd == "generate-menu":
        workouts = _load_workouts(args.workouts)
        plan = generate_menu(workouts, api_key)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        print(f"✅ 週間メニューを保存しました → {args.output}")
        print(f"   対象週: {plan['weekStart']} 〜 {plan['weekEnd']}")
        print(f"   トレーニング日数: {len(plan['days'])} 日")

    elif args.cmd == "generate-feedback":
        workouts = _load_workouts(args.workouts)
        with open(args.plan, encoding="utf-8") as f:
            plan = json.load(f)
        fb = generate_feedback(workouts, plan, args.date, api_key)
        if "feedbacks" not in plan:
            plan["feedbacks"] = {}
        plan["feedbacks"][args.date] = fb
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        print(f"✅ フィードバックを追記しました → {args.output}")
        print(f"   日付: {args.date}  評価: {'★' * fb['rating']}{'☆' * (5 - fb['rating'])}")


if __name__ == "__main__":
    main()
