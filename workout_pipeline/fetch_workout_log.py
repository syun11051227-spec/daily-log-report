"""
Google Sheets から筋トレログ・目標を取得する
"""
from __future__ import annotations
import os
import json
import gspread
from google.oauth2.service_account import Credentials


SCOPES        = ['https://www.googleapis.com/auth/spreadsheets.readonly']
SPREADSHEET_ID = os.environ['GOOGLE_SHEETS_SPREADSHEET_ID']

SHEET_LOG   = 'workout_log'
SHEET_GOALS = 'goals'
HEADER_ROWS = 3  # 列名・内容・例の3行をスキップ


def _get_client():
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


def fetch_workout_log() -> list[dict]:
    """
    workout_log シートの全データを取得して返す。
    各行を dict に変換する。列レイアウト:
      A(空) | B:date | C:workout_type | D:duration | E:exercise_name |
      F:muscle | G:set_number | H:weight | I:unit | J:reps |
      K:is_seconds | L:rpe | M:memo
    """
    client = _get_client()
    try:
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_LOG)
    except Exception as e:
        print(f'[fetch_workout_log] "{SHEET_LOG}" シートが見つかりません: {e}')
        return []
    rows   = sheet.get_all_values()[HEADER_ROWS:]  # ヘッダー3行をスキップ

    records = []
    for row in rows:
        # B列(index=1)が空ならスキップ
        if len(row) < 2 or not row[1].strip():
            continue
        try:
            records.append({
                'date':          row[1].strip(),
                'workout_type':  row[2].strip()  if len(row) > 2  else '',
                'duration':      int(row[3])      if len(row) > 3  and row[3] else 0,
                'exercise_name': row[4].strip()  if len(row) > 4  else '',
                'muscle':        row[5].strip()  if len(row) > 5  else '',
                'set_number':    int(row[6])      if len(row) > 6  and row[6] else 0,
                'weight':        float(row[7])    if len(row) > 7  and row[7] else None,
                'unit':          row[8].strip()  if len(row) > 8  else 'kg',
                'reps':          int(row[9])      if len(row) > 9  and row[9] else None,
                'is_seconds':    row[10].strip().upper() == 'TRUE' if len(row) > 10 else False,
                'rpe':           int(row[11])     if len(row) > 11 and row[11] else None,
                'memo':          row[12].strip()  if len(row) > 12 else '',
            })
        except (ValueError, IndexError) as e:
            print(f'[skip] 行パースエラー: {row[:5]} → {e}')
            continue

    return records


def fetch_goals() -> list[dict]:
    """
    goals シートから長期目標を取得する。列レイアウト:
      A(空) | B:exercise_name | C:goal_type | D:target_value |
      E:unit | F:target_date | G:note
    シートが存在しない場合は空リストを返す。
    """
    client = _get_client()
    try:
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_GOALS)
    except Exception as e:
        print(f'[fetch_goals] "{SHEET_GOALS}" シートが見つかりません（スキップ）: {e}')
        return []
    rows   = sheet.get_all_values()[HEADER_ROWS:]

    goals = []
    for row in rows:
        if len(row) < 3 or not row[2].strip():  # C列(goal_type)が空ならスキップ
            continue
        try:
            goals.append({
                'exercise_name': row[1].strip()  if len(row) > 1 else '',
                'goal_type':     row[2].strip()  if len(row) > 2 else '',
                'target_value':  float(row[3])   if len(row) > 3 and row[3] else None,
                'unit':          row[4].strip()  if len(row) > 4 else '',
                'target_date':   row[5].strip()  if len(row) > 5 else '',
                'note':          row[6].strip()  if len(row) > 6 else '',
            })
        except (ValueError, IndexError) as e:
            print(f'[skip] goalsパースエラー: {row} → {e}')
            continue

    return goals


if __name__ == '__main__':
    logs  = fetch_workout_log()
    goals = fetch_goals()
    print(f'workout_log: {len(logs)} 行取得')
    if logs:
        dates = sorted({r['date'] for r in logs})
        print(f'  期間: {dates[0]} 〜 {dates[-1]}')
    print(f'goals: {len(goals)} 件取得')
    for g in goals:
        print(f'  {g}')
