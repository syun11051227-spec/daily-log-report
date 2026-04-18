#!/usr/bin/env python3
"""
DailyLog シートを Google Sheets API から読み込み、ターミナルに表示する。

前提（Google Cloud Console）:
  1. プロジェクトを作成し「Google Sheets API」を有効化
  2. OAuth クライアント ID（デスクトップアプリ）を作成
  3. JSON をダウンロードし、このディレクトリに credentials.json として保存

環境変数:
  GOOGLE_SHEETS_SPREADSHEET_ID … スプレッドシート URL の /d/ と /edit の間の ID

初回実行時にブラウザが開き、承認後 token.json が生成される。
"""

from __future__ import annotations

import os
import sys

import pandas as pd

from daily_log import fetch_values, rows_to_dataframe


def main() -> None:
    sid = os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID", "").strip()
    if not sid:
        print(
            "環境変数 GOOGLE_SHEETS_SPREADSHEET_ID が未設定です。\n"
            "例: export GOOGLE_SHEETS_SPREADSHEET_ID='xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'",
            file=sys.stderr,
        )
        sys.exit(1)

    rows = fetch_values(sid)
    df = rows_to_dataframe(rows)

    if df.empty:
        print("DailyLog にデータがありません（または B:H が空です）。")
        return

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 40)

    print(df.to_string(index=False))
    print(f"\n行数: {len(df)}  期間: {df['date'].min()} — {df['date'].max()}")


if __name__ == "__main__":
    main()
