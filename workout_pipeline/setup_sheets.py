"""
スプレッドシートのヘッダー行を正しく初期化するスクリプト。
初回セットアップ時や、手動入力でズレが生じた場合に実行する。

実行例:
  python setup_sheets.py
"""
from __future__ import annotations

import json
import os

import gspread
from google.oauth2.service_account import Credentials


SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = os.environ['GOOGLE_SHEETS_SPREADSHEET_ID']

# ヘッダー行は 2 行（列名 + 説明）に統一。例行は廃止。
HEADER_ROWS = 2


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


# ── 各シートのヘッダー定義 ────────────────────────────────

WEEKLY_MENU_HEADERS = [
    # 行1: 列名（英語）
    ['', 'week_start', 'week_end', 'training_date', 'workout_type',
     'exercise_name', 'target_sets', 'target_reps', 'target_weight',
     'coach_note', 'coach_message', 'generated_at'],
    # 行2: 説明（日本語）
    ['', '週の開始日', '週の終了日', 'トレーニング予定日', '部位',
     '種目名', '目標セット数', '目標回数', '目標重量',
     '種目ごとのコーチ指示', '週全体へのメッセージ', '生成日時'],
]

COACH_FEEDBACK_HEADERS = [
    # 行1: 列名（英語）
    ['', 'training_date', 'rating', 'feedback_text',
     'point_type', 'point_text', 'generated_at'],
    # 行2: 説明（日本語）
    ['', '対象日', '評価（1〜5）', 'メインコメント',
     'ポイント種別（positive / improve）', 'ポイント内容', '生成日時'],
]

WORKOUT_LOG_HEADERS = [
    # 行1: 列名（英語）
    ['', 'date', 'workout_type', 'duration', 'exercise_name',
     'muscle', 'set_number', 'weight', 'unit', 'reps',
     'is_seconds', 'rpe', 'memo'],
    # 行2: 説明（日本語）
    ['', '日付', '部位', 'トレーニング時間（分）', '種目名',
     '筋肉部位', 'セット番号', '重量', '単位', '回数 or 秒',
     '秒種目か', '強度（1〜3）', 'メモ'],
]

GOALS_HEADERS = [
    # 行1: 列名（英語）
    ['', 'exercise_name', 'goal_type', 'target_value',
     'unit', 'target_date', 'note'],
    # 行2: 説明（日本語）
    ['', '種目名（空欄=全体目標）', '目標の種類', '目標数値',
     '単位', '達成したい日付', '補足'],
]


# ── セットアップ処理 ──────────────────────────────────────

def setup_sheet(sheet: gspread.Worksheet,
                headers: list[list],
                preserve_data: bool = True) -> None:
    """
    シートのヘッダー行を上書きする。
    preserve_data=True の場合、HEADER_ROWS 以降のデータ行は保持する。
    """
    col_count = max(len(h) for h in headers)

    if preserve_data:
        # ヘッダー行のみ上書き（A1 から HEADER_ROWS 行分）
        sheet.update(
            range_name=f'A1:{chr(ord("A") + col_count - 1)}{len(headers)}',
            values=headers,
            value_input_option='USER_ENTERED',
        )
        print(f'  ヘッダー {len(headers)} 行を更新しました（データは保持）')
    else:
        # 全クリアして再構築
        sheet.clear()
        sheet.update(range_name='A1', values=headers,
                     value_input_option='USER_ENTERED')
        print(f'  シートをクリアしてヘッダーを書き込みました')


def fix_row3_in_data_sheets(client: gspread.Client) -> None:
    """
    weekly_menu / coach_feedback の row 3（誤って入力された例行）を削除する。
    Python が書いたデータ（row 4+）は保持する。
    HEADER_ROWS が 3 から 2 に変わるため、row 3 が不要になる。
    """
    ss = client.open_by_key(SPREADSHEET_ID)

    for sheet_name in ('weekly_menu', 'coach_feedback', 'workout_log', 'goals'):
        try:
            sheet     = ss.worksheet(sheet_name)
            all_rows  = sheet.get_all_values()
            if len(all_rows) >= 3:
                # row 3 の内容を確認（例行かどうかはチェックせず無条件削除）
                sheet.delete_rows(3)
                print(f'  {sheet_name}: row 3（例行）を削除しました')
            else:
                print(f'  {sheet_name}: row 3 がありません（スキップ）')
        except gspread.WorksheetNotFound:
            print(f'  {sheet_name}: シートが見つかりません（スキップ）')


def main() -> None:
    print('=== スプレッドシート初期化 ===')
    client = _client()
    ss     = client.open_by_key(SPREADSHEET_ID)

    # ── Step 1: row 3（例行）を削除 ──────────────────────
    print('\n[1/3] 例行（row 3）を削除中…')
    fix_row3_in_data_sheets(client)

    # ── Step 2: ヘッダー行を正しい内容で上書き ──────────
    print('\n[2/3] ヘッダー行を更新中…')
    for sheet_name, headers in [
        ('weekly_menu',     WEEKLY_MENU_HEADERS),
        ('coach_feedback',  COACH_FEEDBACK_HEADERS),
        ('workout_log',     WORKOUT_LOG_HEADERS),
        ('goals',           GOALS_HEADERS),
    ]:
        try:
            sheet = ss.worksheet(sheet_name)
            print(f'  {sheet_name}:')
            setup_sheet(sheet, headers, preserve_data=True)
        except gspread.WorksheetNotFound:
            print(f'  {sheet_name}: シートが見つかりません（スキップ）')

    # ── Step 3: weekly_menu の旧テストデータを削除 ───────
    print('\n[3/3] weekly_menu の旧テストデータを削除中…')
    try:
        from datetime import date, timedelta
        sheet      = ss.worksheet('weekly_menu')
        all_rows   = sheet.get_all_values()
        today      = date.today()
        next_mon   = today - timedelta(days=today.weekday()) + timedelta(weeks=1)
        keep_from  = (next_mon - timedelta(weeks=4)).isoformat()

        to_delete = [
            i + 1
            for i in range(len(all_rows) - 1, HEADER_ROWS - 1, -1)
            if len(all_rows[i]) > 1
            and all_rows[i][1]               # B列(week_start)が空でない
            and all_rows[i][1] < keep_from   # 4週前より古い
        ]
        if to_delete:
            # 連続する行をグループ化して削除
            groups: list[tuple[int, int]] = []
            s = e = to_delete[0]
            for r in to_delete[1:]:
                if r == s - 1:
                    s = r
                else:
                    groups.append((s, e))
                    s = e = r
            groups.append((s, e))
            for gs, ge in groups:
                sheet.delete_rows(gs, ge)
            print(f'  {len(to_delete)} 行の旧データを削除しました')
        else:
            print('  削除対象なし')
    except Exception as e:
        print(f'  weekly_menu クリーンアップ中にエラー: {e}')

    print('\n=== 完了 ===')
    print('HEADER_ROWS を 3 → 2 に変更したので、')
    print('fetch_workout_log.py と generate_workout_plan.py の')
    print('HEADER_ROWS = 3 を HEADER_ROWS = 2 に変更してください。')


if __name__ == '__main__':
    main()
