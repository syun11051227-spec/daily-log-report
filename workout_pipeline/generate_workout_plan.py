"""
メインエントリーポイント

処理の流れ:
  1. Google Sheets から workout_log・goals を取得
  2. Python でデータ分析・プロンプト生成
  3. Gemini API でメニュー・フィードバックを生成
  4. 結果を weekly_menu・coach_feedback シートに書き込む

列レイアウト（B列スタート・A列は使用しない）:
  weekly_menu    : B:week_start C:week_end D:training_date E:workout_type
                   F:exercise_name G:target_sets H:target_reps I:target_weight
                   J:coach_note K:coach_message L:generated_at
  coach_feedback : B:training_date C:rating D:feedback_text
                   E:point_type F:point_text G:generated_at
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


# ── ユーティリティ ────────────────────────────────────────

def _s(v) -> str:
    """値を文字列に変換する。None は空文字に変換。"""
    return '' if v is None else str(v)


def _next_row(sheet: gspread.Worksheet) -> int:
    """データを追記する次の行番号（1-indexed）を返す。"""
    return len(sheet.get_all_values()) + 1


def _delete_rows_matching(sheet: gspread.Worksheet,
                          col_idx: int, key: str) -> int:
    """
    col_idx 列の値が key と一致するデータ行を削除する。
    連続する行をグループ化して一括 API 呼び出しにする。
    col_idx はシート全体の 0-based インデックス（A=0, B=1, ...）。
    """
    all_rows = sheet.get_all_values()
    targets = [
        i + 1  # 1-indexed
        for i in range(len(all_rows) - 1, HEADER_ROWS - 1, -1)
        if len(all_rows[i]) > col_idx and all_rows[i][col_idx] == key
    ]
    if not targets:
        return 0

    groups: list[tuple[int, int]] = []
    s = e = targets[0]
    for r in targets[1:]:
        if r == s - 1:
            s = r
        else:
            groups.append((s, e))
            s = e = r
    groups.append((s, e))

    for gs, ge in groups:
        sheet.delete_rows(gs, ge)

    return len(targets)


def _write_rows(sheet: gspread.Worksheet, rows: list[list]) -> None:
    """
    B列スタートで行データを書き込む。
    append_rows は列Aが空の場合にB列からテーブルを検出して
    ズレが生じるため、明示的な範囲指定で update() を使う。
    """
    if not rows:
        return
    next_r = _next_row(sheet)
    # 範囲: B{next_r} から始まる（A列は使用しない）
    sheet.update(
        range_name=f'B{next_r}',
        values=rows,
        value_input_option='USER_ENTERED',
    )


def _next_week_range() -> tuple[str, str]:
    today  = date.today()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=1)
    return monday.isoformat(), (monday + timedelta(days=6)).isoformat()


# ── weekly_menu 書き込み ──────────────────────────────────

def write_weekly_menu(client: gspread.Client, plan: list[dict],
                      coach_message: str,
                      week_start: str, week_end: str) -> None:
    """weekly_menu シートへ翌週メニューを書き込む。同週の既存データは上書き。
    列レイアウト（B列スタート）:
      B:week_start | C:week_end | D:training_date | E:workout_type |
      F:exercise_name | G:target_sets | H:target_reps | I:target_weight |
      J:coach_note | K:coach_message | L:generated_at
    """
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_MENU)
    now   = date.today().isoformat()

    # 同じ week_start の既存行を削除（B列 = col_idx=1 で検索）
    deleted = _delete_rows_matching(sheet, col_idx=1, key=week_start)
    if deleted:
        print(f'[menu] 既存 {deleted} 行を削除しました', file=sys.stderr)

    rows: list[list] = []
    for day in plan:
        for ex in day.get('exercises', []):
            rows.append([
                week_start,                        # B
                week_end,                          # C
                _s(day.get('training_date')),      # D
                _s(day.get('workout_type')),       # E
                _s(ex.get('name')),                # F
                _s(ex.get('target_sets')),         # G
                _s(ex.get('target_reps')),         # H
                _s(ex.get('target_weight')),       # I
                _s(ex.get('coach_note')),          # J
                coach_message,                     # K（後で1行目のみに）
                now,                               # L
            ])

    if not rows:
        print('[menu] 書き込むデータがありません', file=sys.stderr)
        return

    # coach_message は全体で最初の 1 行のみ
    for i in range(1, len(rows)):
        rows[i][9] = ''  # index 9 = K列

    _write_rows(sheet, rows)
    print(f'[menu] {len(rows)} 行を B 列スタートで書き込みました', file=sys.stderr)


# ── coach_feedback 書き込み ───────────────────────────────

def write_feedback(client: gspread.Client,
                   feedback: dict, training_date: str) -> None:
    """coach_feedback シートへフィードバックを書き込む。
    列レイアウト（B列スタート）:
      B:training_date | C:rating | D:feedback_text |
      E:point_type | F:point_text | G:generated_at
    """
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_FEEDBACK)
    now   = date.today().isoformat()

    # 同じ training_date の既存行を削除（B列 = col_idx=1 で検索）
    deleted = _delete_rows_matching(sheet, col_idx=1, key=training_date)
    if deleted:
        print(f'[fb] 既存 {deleted} 行を削除しました', file=sys.stderr)

    rows: list[list] = []
    points = feedback.get('points', [])

    if points:
        for idx, pt in enumerate(points):
            rows.append([
                training_date,                                      # B
                _s(feedback.get('rating')) if idx == 0 else '',    # C
                _s(feedback.get('text'))   if idx == 0 else '',    # D
                _s(pt.get('type')),                                 # E
                _s(pt.get('text')),                                 # F
                now,                                                # G
            ])
    else:
        rows.append([
            training_date,
            _s(feedback.get('rating')),
            _s(feedback.get('text')),
            '', '', now,
        ])

    _write_rows(sheet, rows)
    print(f'[fb] {len(rows)} 行を B 列スタートで書き込みました', file=sys.stderr)


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

    # デバッグ：AIレスポンスの最初の種目を確認
    try:
        first_ex = ai_result['weekly_plan'][0]['exercises'][0]
        print(f'[debug] 最初の種目: {json.dumps(first_ex, ensure_ascii=False)}',
              file=sys.stderr)
    except (KeyError, IndexError):
        pass

    week_start, week_end = _next_week_range()
    client = _client()

    write_weekly_menu(
        client,
        plan          = ai_result.get('weekly_plan', []),
        coach_message = ai_result.get('coach_message', ''),
        week_start    = week_start,
        week_end      = week_end,
    )

    recent_date = sorted({r['date'] for r in records}, reverse=True)[0]
    write_feedback(client, ai_result.get('feedback', {}), recent_date)

    print('[main] 完了', file=sys.stderr)
    print(json.dumps(ai_result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
