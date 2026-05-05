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


# ── 設定 ─────────────────────────────────────────────────

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = os.environ['GOOGLE_SHEETS_SPREADSHEET_ID']

SHEET_MENU     = 'weekly_menu'
SHEET_FEEDBACK = 'coach_feedback'
HEADER_ROWS    = 2   # 列名・説明の2行（setup_sheets.py 実行後）


# ── 認証 ─────────────────────────────────────────────────

def _client():
    creds_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if creds_json:
        creds = Credentials.from_service_account_info(
            json.loads(creds_json), scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file(
            os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', 'credentials.json'),
            scopes=SCOPES)
    return gspread.authorize(creds)


# ── 汎用ユーティリティ ────────────────────────────────────

def _delete_rows_matching(sheet: gspread.Worksheet,
                          col_idx: int, key: str) -> int:
    """
    col_idx 列の値が key と一致するデータ行（HEADER_ROWS 以降）を削除する。
    連続する行をグループ化して一括 API 呼び出しにすることで
    レート制限・インデックスズレを回避する。
    削除した行数を返す。
    """
    all_rows = sheet.get_all_values()
    # 削除対象を 1-indexed の行番号リストで収集（逆順）
    targets = [
        i + 1
        for i in range(len(all_rows) - 1, HEADER_ROWS - 1, -1)
        if len(all_rows[i]) > col_idx and all_rows[i][col_idx] == key
    ]
    if not targets:
        return 0

    # 連続する番号をグループ化 → (start, end) タプルのリスト（逆順）
    groups: list[tuple[int, int]] = []
    run_end = run_start = targets[0]
    for r in targets[1:]:
        if r == run_start - 1:        # 連続している
            run_start = r
        else:
            groups.append((run_start, run_end))
            run_end = run_start = r
    groups.append((run_start, run_end))

    for start, end in groups:
        sheet.delete_rows(start, end)

    return len(targets)


def _next_week_range() -> tuple[str, str]:
    """翌週月曜〜日曜の ISO 日付を返す"""
    today  = date.today()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=1)
    return monday.isoformat(), (monday + timedelta(days=6)).isoformat()


# ── weekly_menu 書き込み ──────────────────────────────────

def write_weekly_menu(client: gspread.Client, plan: list[dict],
                      coach_message: str,
                      week_start: str, week_end: str) -> None:
    """weekly_menu シートへ翌週メニューを書き込む。同週の既存データは上書き。"""
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_MENU)
    now   = date.today().isoformat()

    # 同じ week_start の既存行を一括削除
    deleted = _delete_rows_matching(sheet, col_idx=1, key=week_start)
    if deleted:
        print(f'[menu] 既存 {deleted} 行を削除しました', file=sys.stderr)

    # 書き込む行を構築
    #   A(空) | B:week_start | C:week_end | D:training_date | E:workout_type
    #   F:exercise_name | G:target_sets | H:target_reps | I:target_weight
    #   J:coach_note | K:coach_message | L:generated_at
    rows: list[list] = []
    for day in plan:
        for ex in day.get('exercises', []):
            rows.append([
                '',
                week_start,
                week_end,
                day.get('training_date', ''),
                day.get('workout_type',  ''),
                ex.get('name',           ''),
                ex.get('target_sets',    ''),
                ex.get('target_reps',    ''),
                ex.get('target_weight',  ''),
                ex.get('coach_note',     ''),
                coach_message,        # 最初の行だけ（後で上書き）
                now,
            ])

    if not rows:
        print('[menu] 書き込むデータがありません', file=sys.stderr)
        return

    # coach_message は全体で最初の 1 行のみ
    for i in range(1, len(rows)):
        rows[i][10] = ''

    sheet.append_rows(rows, value_input_option='USER_ENTERED')
    print(f'[menu] {len(rows)} 行を書き込みました', file=sys.stderr)


# ── coach_feedback 書き込み ───────────────────────────────

def write_feedback(client: gspread.Client,
                   feedback: dict, training_date: str) -> None:
    """
    coach_feedback シートへフィードバックを書き込む。
    同じ training_date の既存行は上書き（削除→追記）。
    列レイアウト:
      A(空) | B:training_date | C:rating | D:feedback_text
      E:point_type | F:point_text | G:generated_at
    """
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_FEEDBACK)
    now   = date.today().isoformat()

    # 同じ training_date の既存行を一括削除
    deleted = _delete_rows_matching(sheet, col_idx=1, key=training_date)
    if deleted:
        print(f'[fb] 既存 {deleted} 行を削除しました', file=sys.stderr)

    # 書き込む行を構築（ポイントごとに 1 行）
    rows: list[list] = []
    points = feedback.get('points', [])

    if points:
        for idx, pt in enumerate(points):
            rows.append([
                '',
                training_date,
                feedback.get('rating', '') if idx == 0 else '',
                feedback.get('text',   '') if idx == 0 else '',
                pt.get('type', ''),
                pt.get('text', ''),
                now,
            ])
    else:
        # ポイントなし → 本文だけ 1 行
        rows.append([
            '', training_date,
            feedback.get('rating', ''),
            feedback.get('text',   ''),
            '', '', now,
        ])

    sheet.append_rows(rows, value_input_option='USER_ENTERED')
    print(f'[fb] {len(rows)} 行を書き込みました', file=sys.stderr)


# ── メイン ────────────────────────────────────────────────

def main() -> None:
    print('[main] データ取得中…', file=sys.stderr)
    records = fetch_workout_log()
    goals   = fetch_goals()

    if not records:
        print('[main] workout_log にデータがありません。終了します。', file=sys.stderr)
        sys.exit(0)

    print(f'[main] {len(records)} 行のログを取得しました', file=sys.stderr)

    result = analyze(records, goals)
    prompt = build_prompt(result)
    print('[main] プロンプト生成完了', file=sys.stderr)

    print('[main] Gemini でメニュー生成中…', file=sys.stderr)
    ai_result = generate(prompt)
    if ai_result is None:
        print('[main] Gemini 生成失敗。終了します。', file=sys.stderr)
        sys.exit(1)

    week_start, week_end = _next_week_range()
    client = _client()

    write_weekly_menu(
        client,
        plan          = ai_result.get('weekly_plan', []),
        coach_message = ai_result.get('coach_message', ''),
        week_start    = week_start,
        week_end      = week_end,
    )

    # 直近トレーニング日のフィードバック
    recent_date = sorted({r['date'] for r in records}, reverse=True)[0]
    write_feedback(client, ai_result.get('feedback', {}), recent_date)

    print('[main] 完了', file=sys.stderr)
    print(json.dumps(ai_result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
