"""
メインエントリーポイント

処理の流れ:
  1. Google Sheets から workout_log・goals を取得
  2. Python でデータ分析・プロンプト生成
  3. Gemini API でメニュー・フィードバックを生成
  4. 結果を weekly_menu・coach_feedback シートに書き込む

実行例:
  python generate_workout_plan.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta

import gspread
from google.oauth2.service_account import Credentials

from fetch_workout_log import fetch_workout_log, fetch_goals
from workout_analyze   import analyze, build_prompt
from coach_llm         import generate


# ── Sheets 書き込み用クライアント ─────────────────────────

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',   # 読み書き
]
SPREADSHEET_ID = os.environ['GOOGLE_SHEETS_SPREADSHEET_ID']

SHEET_MENU     = 'weekly_menu'
SHEET_FEEDBACK = 'coach_feedback'
HEADER_ROWS    = 3


def _write_client():
    creds_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if creds_json:
        info  = json.loads(creds_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file(
            os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', 'credentials.json'),
            scopes=SCOPES,
        )
    return gspread.authorize(creds)


# ── Sheets への書き込み ───────────────────────────────────

def _next_week_range():
    """翌週月曜〜日曜の日付を返す"""
    today  = date.today()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=1)
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


def write_weekly_menu(client: gspread.Client, plan: list[dict],
                      coach_message: str, week_start: str, week_end: str):
    """weekly_menu シートに翌週メニューを書き込む"""
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_MENU)
    now   = date.today().isoformat()

    # 同じ week_start の既存行を削除（再実行時の重複防止）
    all_rows = sheet.get_all_values()
    for i in range(len(all_rows) - 1, HEADER_ROWS - 1, -1):
        if len(all_rows[i]) > 1 and all_rows[i][1] == week_start:
            sheet.delete_rows(i + 1)

    # 新しい行を追加
    rows = []
    for day in plan:
        for ex in day.get('exercises', []):
            rows.append([
                '',                             # A列（空）
                week_start,                     # B: week_start
                week_end,                       # C: week_end
                day.get('training_date', ''),   # D: training_date
                day.get('workout_type', ''),    # E: workout_type
                ex.get('name', ''),             # F: exercise_name
                ex.get('target_sets', ''),      # G: target_sets
                ex.get('target_reps', ''),      # H: target_reps
                ex.get('target_weight', ''),    # I: target_weight
                ex.get('coach_note', ''),       # J: coach_note
                coach_message,                  # K: coach_message（最初の行のみ有効）
                now,                            # L: generated_at
            ])

    # coach_message は最初の1行のみ
    for i in range(1, len(rows)):
        rows[i][10] = ''

    if rows:
        start_row = sheet.get_all_values().__len__() + 1
        sheet.append_rows(rows, value_input_option='USER_ENTERED')
    print(f'[main] weekly_menu に {len(rows)} 行書き込みました', file=sys.stderr)


def write_feedback(client: gspread.Client, feedback: dict, training_date: str):
    """coach_feedback シートにフィードバックを書き込む"""
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_FEEDBACK)
    now   = date.today().isoformat()

    # 同じ training_date の既存行を削除
    all_rows = sheet.get_all_values()
    for i in range(len(all_rows) - 1, HEADER_ROWS - 1, -1):
        if len(all_rows[i]) > 1 and all_rows[i][1] == training_date:
            sheet.delete_rows(i + 1)

    # フィードバック本文 + ポイントを1行ずつ書き込む
    rows = []
    points = feedback.get('points', [])
    for idx, pt in enumerate(points):
        rows.append([
            '',                                    # A列（空）
            training_date,                         # B: training_date
            feedback.get('rating', '') if idx == 0 else '',  # C: rating
            feedback.get('text', '')   if idx == 0 else '',  # D: feedback_text
            pt.get('type', ''),                    # E: point_type
            pt.get('text', ''),                    # F: point_text
            now,                                   # G: generated_at
        ])

    if not rows:  # ポイントなしの場合は1行だけ書く
        rows.append([
            '', training_date,
            feedback.get('rating', ''),
            feedback.get('text', ''),
            '', '', now,
        ])

    sheet.append_rows(rows, value_input_option='USER_ENTERED')
    print(f'[main] coach_feedback に {len(rows)} 行書き込みました', file=sys.stderr)


# ── メイン処理 ────────────────────────────────────────────

def main():
    print('[main] データ取得中…', file=sys.stderr)
    records = fetch_workout_log()
    goals   = fetch_goals()

    if not records:
        print('[main] workout_log にデータがありません。処理を終了します。', file=sys.stderr)
        sys.exit(0)

    print(f'[main] {len(records)} 行のログを取得しました', file=sys.stderr)

    # 分析・プロンプト生成
    result = analyze(records, goals)
    prompt = build_prompt(result)
    print('[main] プロンプト生成完了', file=sys.stderr)

    # Gemini API 呼び出し
    print('[main] Gemini でメニュー生成中…', file=sys.stderr)
    ai_result = generate(prompt)

    if ai_result is None:
        print('[main] Gemini 生成失敗。処理を終了します。', file=sys.stderr)
        sys.exit(1)

    # Sheets に書き込む
    week_start, week_end = _next_week_range()
    client = _write_client()

    write_weekly_menu(
        client,
        plan          = ai_result.get('weekly_plan', []),
        coach_message = ai_result.get('coach_message', ''),
        week_start    = week_start,
        week_end      = week_end,
    )

    # 直近のトレーニング日のフィードバックを書き込む
    recent_dates = sorted({r['date'] for r in records}, reverse=True)
    if recent_dates:
        write_feedback(client, ai_result.get('feedback', {}), recent_dates[0])

    print('[main] 完了', file=sys.stderr)
    print(json.dumps(ai_result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
