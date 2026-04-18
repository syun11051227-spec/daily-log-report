"""DailyLog シートの読み取り（fetch_daily_log.py と週次レポート生成で共用）。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
from google.auth.credentials import Credentials
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SHEET_NAME = "DailyLog"
RANGE = f"{SHEET_NAME}!B:H"
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"


def _base_dir() -> Path:
    return Path(__file__).resolve().parent


def _credentials_from_service_account() -> Credentials | None:
    """CI 等: 環境変数または標準の鍵ファイルパスからサービスアカウント認証情報を作る。"""
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(
                f"環境変数 GOOGLE_SERVICE_ACCOUNT_JSON が不正な JSON です: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

    gap = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if gap and Path(gap).is_file():
        return service_account.Credentials.from_service_account_file(gap, scopes=SCOPES)

    return None


def get_credentials() -> Credentials:
    sa = _credentials_from_service_account()
    if sa is not None:
        return sa

    base = _base_dir()
    token_path = base / TOKEN_FILE
    cred_path = base / CREDENTIALS_FILE

    creds: UserCredentials | None = None
    if token_path.is_file():
        creds = UserCredentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not cred_path.is_file():
                print(
                    f"エラー: {cred_path} がありません。\n"
                    "Google Cloud Console でデスクトップ用 OAuth クライアントの JSON を\n"
                    "このファイル名で保存してください。\n"
                    "GitHub Actions では Secrets の GOOGLE_SERVICE_ACCOUNT_JSON を設定してください。",
                    file=sys.stderr,
                )
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), SCOPES)
            creds = flow.run_local_server(
                port=0,
                open_browser=True,
                timeout_seconds=300,
                authorization_prompt_message=(
                    "\nブラウザが自動で開かない場合は、下の URL をコピーして "
                    "この Mac のブラウザに貼ってください。\n"
                    "許可が終わるまでこのウィンドウを閉じず、別のコマンドを打たないでください。\n"
                ),
                success_message="認証が完了しました。このターミナルに戻ってください。",
            )
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return creds


def fetch_values(spreadsheet_id: str) -> list[list[str]]:
    creds = get_credentials()
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=RANGE)
        .execute()
    )
    return result.get("values", [])


def rows_to_dataframe(rows: list[list[str]]) -> pd.DataFrame:
    columns = ["date", "category", "item", "value", "unit", "note_pace", "note_updated"]
    if not rows:
        return pd.DataFrame(columns=columns)

    start = 0
    if rows[0] and str(rows[0][0]).strip() in ("日付", "date", "Date"):
        start = 1

    data = rows[start:]
    records: list[dict[str, str]] = []
    for r in data:
        padded = (r + [""] * len(columns))[: len(columns)]
        row_dict = dict(zip(columns, padded))
        if not any(str(v).strip() for v in row_dict.values()):
            continue
        records.append(row_dict)

    df = pd.DataFrame(records)
    if df.empty:
        return df

    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


def load_daily_log(spreadsheet_id: str | None = None) -> pd.DataFrame:
    sid = (spreadsheet_id or os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID", "")).strip()
    if not sid:
        print(
            "環境変数 GOOGLE_SHEETS_SPREADSHEET_ID が未設定です。",
            file=sys.stderr,
        )
        sys.exit(1)
    return rows_to_dataframe(fetch_values(sid))
