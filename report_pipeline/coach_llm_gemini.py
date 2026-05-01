"""案 A: Gemini（Google AI Studio API キー）でコーチコメントを生成。

環境変数:
  GEMINI_API_KEY または GOOGLE_API_KEY … いずれか（[API key ドキュメント](https://ai.google.dev/gemini-api/docs/api-key)）
  GEMINI_MODEL … 省略時 gemini-2.5-flash

失敗時は None を返し、呼び出し側でルールベースにフォールバックする。
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

from coach_comments import (
    COACH_LLM_RULES_SNIPPET,
    CoachCard,
    month_summary_for_llm,
    week_summary_for_llm,
    year_summary_for_llm,
)
from week_aggregate import MonthReport, WeekReport, YearReport

_COACH_META: dict[str, tuple[str, str]] = {
    "uchan": ("内村さん", "伴走のリーダー · メンタル維持"),
    "hotaru": ("ホタル", "脱力系アナリスト"),
    "mugikoge": ("むぎちゃ ＆ おこげ", "癒やしの家族"),
    "laoshi": ("老師", "駐在の賢者"),
    "shuzo": ("修造コーチ", "太陽の応援団"),
}

_COACH_ORDER = ("uchan", "hotaru", "mugikoge", "laoshi", "shuzo")

_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "coaches": {
            "type": "array",
            "description": "週次データに基づき選ぶコーチちょうど2名",
            "items": {
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "enum": list(_COACH_ORDER),
                    },
                    "lines": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 4,
                    },
                },
                "required": ["slug", "lines"],
            },
            "minItems": 2,
            "maxItems": 2,
        }
    },
    "required": ["coaches"],
}


def _gemini_api_key() -> str | None:
    return (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or "").strip() or None


def try_gemini_coach_cards(rep: WeekReport) -> list[CoachCard] | None:
    """Gemini でコーチ2名分を生成。キー未設定・API 失敗・JSON 不正時は None。"""
    key = _gemini_api_key()
    if not key:
        return None

    model = (os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash").strip()

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print(
            "coach_llm_gemini: google-genai が未インストールです。pip install google-genai",
            file=sys.stderr,
        )
        return None

    data = week_summary_for_llm(rep)
    data_json = json.dumps(data, ensure_ascii=False, indent=2)

    system = f"""あなたは週次自己成長レポート用のコーチ台本ライターです。
次のキャラクター設定と振る舞いルールに厳密に従ってください。

{COACH_LLM_RULES_SNIPPET}

追加ルール:
- 出力はスキーマに従う JSON のみ（説明文や Markdown 禁止）。
- coaches はちょうど 2 要素。slug は重複禁止。5 名からデータに合う 2 名を選ぶ。
- lines は日本語。各コーチ 2〜4 行。事実は次の JSON の数値・事実のみを使い、捏造しない。
- mugikoge を選んだら 1 行目は必ず「むぎむー！」「こげげー！」を含める。別行で（）の犬視点メッセージを入れる。
- 内村: 丁寧語「〜ですねぇ」。修造: 短く熱い口調。老師: 「〜ですな」調。ホタル: 明るく脱力寄り。"""

    user = f"""以下の週次データ JSON を読み、コーチを 2 名選んでセリフを書いてください。

週次データ:
{data_json}
"""

    client = genai.Client(api_key=key)
    try:
        response = client.models.generate_content(
            model=model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_json_schema=_RESPONSE_JSON_SCHEMA,
                temperature=0.9,
            ),
        )
    except Exception as exc:
        print(f"coach_llm_gemini: API エラー: {exc}", file=sys.stderr)
        return None

    raw = (response.text or "").strip()
    if not raw:
        print("coach_llm_gemini: 空レスポンス", file=sys.stderr)
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            print(f"coach_llm_gemini: JSON 解析失敗: {exc}", file=sys.stderr)
            return None

    coaches_raw = parsed.get("coaches")
    if not isinstance(coaches_raw, list) or len(coaches_raw) != 2:
        print("coach_llm_gemini: coaches が 2 要素ではありません", file=sys.stderr)
        return None

    out: list[CoachCard] = []
    seen: set[str] = set()
    for item in coaches_raw:
        if not isinstance(item, dict):
            return None
        slug = str(item.get("slug", "")).strip()
        lines = item.get("lines")
        if slug not in _COACH_META or slug in seen:
            print(f"coach_llm_gemini: 不正 slug または重複: {slug!r}", file=sys.stderr)
            return None
        if not isinstance(lines, list) or len(lines) < 2:
            print("coach_llm_gemini: lines が短すぎます", file=sys.stderr)
            return None
        seen.add(slug)
        text_lines = [str(x).strip() for x in lines if str(x).strip()]
        if len(text_lines) < 2:
            return None
        name, role = _COACH_META[slug]
        out.append(CoachCard(slug=slug, name=name, role=role, lines=tuple(text_lines[:4])))

    order = {s: i for i, s in enumerate(_COACH_ORDER)}
    out.sort(key=lambda c: order.get(c.slug, 99))
    print("coach_llm_gemini: Gemini でコーチコメントを生成しました", file=sys.stderr)
    return out


def try_gemini_coach_cards_month(mrep: MonthReport) -> list[CoachCard] | None:
    """月次サマリーでコーチ2名分を生成。失敗時は None。"""
    key = _gemini_api_key()
    if not key:
        return None

    model = (os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash").strip()

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print(
            "coach_llm_gemini: google-genai が未インストールです。pip install google-genai",
            file=sys.stderr,
        )
        return None

    data = month_summary_for_llm(mrep)
    data_json = json.dumps(data, ensure_ascii=False, indent=2)

    system = f"""あなたは月次自己成長レポート用のコーチ台本ライターです。
次のキャラクター設定と振る舞いルールに厳密に従ってください。

{COACH_LLM_RULES_SNIPPET}

追加ルール:
- 出力はスキーマに従う JSON のみ（説明文や Markdown 禁止）。
- coaches はちょうど 2 要素。slug は重複禁止。5 名からデータに合う 2 名を選ぶ。
- lines は日本語。各コーチ 2〜4 行。事実は次の JSON の数値・事実のみを使い、捏造しない。
- 月次であること（週タイル・月間達成率・先月比など）に言及してよい。
- mugikoge を選んだら 1 行目は必ず「むぎむー！」「こげげー！」を含める。別行で（）の犬視点メッセージを入れる。
- 内村: 丁寧語「〜ですねぇ」。修造: 短く熱い口調。老師: 「〜ですな」調。ホタル: 明るく脱力寄り。"""

    user = f"""以下の月次データ JSON を読み、コーチを 2 名選んでセリフを書いてください。

月次データ:
{data_json}
"""

    client = genai.Client(api_key=key)
    try:
        response = client.models.generate_content(
            model=model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_json_schema=_RESPONSE_JSON_SCHEMA,
                temperature=0.9,
            ),
        )
    except Exception as exc:
        print(f"coach_llm_gemini: API エラー（月次）: {exc}", file=sys.stderr)
        return None

    raw = (response.text or "").strip()
    if not raw:
        print("coach_llm_gemini: 空レスポンス（月次）", file=sys.stderr)
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            print(f"coach_llm_gemini: JSON 解析失敗（月次）: {exc}", file=sys.stderr)
            return None

    coaches_raw = parsed.get("coaches")
    if not isinstance(coaches_raw, list) or len(coaches_raw) != 2:
        print("coach_llm_gemini: coaches が 2 要素ではありません（月次）", file=sys.stderr)
        return None

    out: list[CoachCard] = []
    seen: set[str] = set()
    for item in coaches_raw:
        if not isinstance(item, dict):
            return None
        slug = str(item.get("slug", "")).strip()
        lines = item.get("lines")
        if slug not in _COACH_META or slug in seen:
            print(f"coach_llm_gemini: 不正 slug または重複（月次）: {slug!r}", file=sys.stderr)
            return None
        if not isinstance(lines, list) or len(lines) < 2:
            print("coach_llm_gemini: lines が短すぎます（月次）", file=sys.stderr)
            return None
        seen.add(slug)
        text_lines = [str(x).strip() for x in lines if str(x).strip()]
        if len(text_lines) < 2:
            return None
        name, role = _COACH_META[slug]
        out.append(CoachCard(slug=slug, name=name, role=role, lines=tuple(text_lines[:4])))

    order = {s: i for i, s in enumerate(_COACH_ORDER)}
    out.sort(key=lambda c: order.get(c.slug, 99))
    print("coach_llm_gemini: Gemini で月次コーチコメントを生成しました", file=sys.stderr)
    return out


def try_gemini_coach_cards_year(yrep: YearReport) -> list[CoachCard] | None:
    """年次サマリーでコーチ2名分を生成。失敗時は None。"""
    key = _gemini_api_key()
    if not key:
        return None

    model = (os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash").strip()

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("coach_llm_gemini: google-genai が未インストールです。", file=sys.stderr)
        return None

    data = year_summary_for_llm(yrep)
    data_json = json.dumps(data, ensure_ascii=False, indent=2)

    system = f"""あなたは年次自己成長レポート用のコーチ台本ライターです。
次のキャラクター設定と振る舞いルールに厳密に従ってください。

{COACH_LLM_RULES_SNIPPET}

追加ルール:
- 出力はスキーマに従う JSON のみ（説明文や Markdown 禁止）。
- coaches はちょうど 2 要素。slug は重複禁止。5 名からデータに合う 2 名を選ぶ。
- lines は日本語。各コーチ 2〜4 行。事実は次の JSON の数値・事実のみを使い、捏造しない。
- 年次であること（月別達成率・年間フル日数・前年比など）に言及してよい。
- mugikoge を選んだら 1 行目は必ず「むぎむー！」「こげげー！」を含める。別行で（）の犬視点メッセージを入れる。
- 内村: 丁寧語「〜ですねぇ」。修造: 短く熱い口調。老師: 「〜ですな」調。ホタル: 明るく脱力寄り。"""

    user = f"以下の年次データ JSON を読み、コーチを 2 名選んでセリフを書いてください。\n\n年次データ:\n{data_json}\n"

    client = genai.Client(api_key=key)
    try:
        response = client.models.generate_content(
            model=model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_json_schema=_RESPONSE_JSON_SCHEMA,
                temperature=0.9,
            ),
        )
    except Exception as exc:
        print(f"coach_llm_gemini: API エラー（年次）: {exc}", file=sys.stderr)
        return None

    raw = (response.text or "").strip()
    if not raw:
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            return None

    coaches_raw = parsed.get("coaches")
    if not isinstance(coaches_raw, list) or len(coaches_raw) != 2:
        return None

    out: list[CoachCard] = []
    seen: set[str] = set()
    for item in coaches_raw:
        if not isinstance(item, dict):
            return None
        slug = str(item.get("slug", "")).strip()
        lines = item.get("lines")
        if slug not in _COACH_META or slug in seen:
            return None
        if not isinstance(lines, list) or len(lines) < 2:
            return None
        seen.add(slug)
        text_lines = [str(x).strip() for x in lines if str(x).strip()]
        if len(text_lines) < 2:
            return None
        name, role = _COACH_META[slug]
        out.append(CoachCard(slug=slug, name=name, role=role, lines=tuple(text_lines[:4])))

    order = {s: i for i, s in enumerate(_COACH_ORDER)}
    out.sort(key=lambda c: order.get(c.slug, 99))
    print("coach_llm_gemini: Gemini で年次コーチコメントを生成しました", file=sys.stderr)
    return out
