"""
Gemini API で翌週メニュー・フィードバックを生成する

環境変数:
  GEMINI_API_KEY または GOOGLE_API_KEY
  GEMINI_MODEL  （省略時: gemini-2.5-flash）

失敗時は None を返す。呼び出し側でフォールバックすること。
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any


# ── レスポンス JSON スキーマ ──────────────────────────────

_SCHEMA: dict[str, Any] = {
    'type': 'object',
    'properties': {
        'coach_message': {
            'type': 'string',
            'description': '週全体へのコーチメッセージ（200〜300字）',
        },
        'weekly_plan': {
            'type': 'array',
            'description': '翌週のトレーニング計画（曜日ごと）',
            'items': {
                'type': 'object',
                'properties': {
                    'training_date': {'type': 'string'},
                    'workout_type':  {'type': 'string'},
                    'exercises': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'name':           {'type': 'string'},
                                'target_sets':    {'type': 'integer'},
                                'target_reps':    {'type': 'string'},
                                'target_weight':  {'type': 'string'},
                                'coach_note':     {'type': 'string'},
                            },
                            'required': ['name', 'target_sets', 'target_reps',
                                         'target_weight', 'coach_note'],
                        },
                    },
                },
                'required': ['training_date', 'workout_type', 'exercises'],
            },
        },
        'feedback': {
            'type': 'object',
            'properties': {
                'rating': {'type': 'integer', 'minimum': 1, 'maximum': 5},
                'text':   {'type': 'string'},
                'points': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'type': {'type': 'string', 'enum': ['positive', 'improve']},
                            'text': {'type': 'string'},
                        },
                        'required': ['type', 'text'],
                    },
                },
            },
            'required': ['rating', 'text', 'points'],
        },
    },
    'required': ['coach_message', 'weekly_plan', 'feedback'],
}

_SYSTEM = """あなたはパーソナルトレーニングコーチです。
ユーザーの筋トレデータを分析し、科学的根拠に基づいた翌週メニューとフィードバックを生成します。

原則:
- 漸進性過負荷：前回比 +2.5〜5kg または +1〜2rep を目安に設定する
- RPE平均が2.5以上の種目は重量を据え置きまたは減量を検討する
- 長期目標の達成から逆算した週次目標を設定する
- coach_note は具体的な根拠（数値・生理学的理由）を含める
- 出力はスキーマに従う JSON のみ（説明文・Markdown禁止）
- 数値は捏造しない。データにある事実のみを使う"""


def _api_key() -> str | None:
    return (
        os.environ.get('GEMINI_API_KEY') or
        os.environ.get('GOOGLE_API_KEY') or ''
    ).strip() or None


def _parse_json(raw: str) -> dict | None:
    """JSON 文字列をパースする。コードブロックがあれば除去して再試行。"""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = re.sub(r'^```(?:json)?\s*', '', raw.strip())
        cleaned = re.sub(r'\s*```\s*$', '', cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            print(f'[coach_llm] JSON 解析失敗: {e}', file=sys.stderr)
            return None


def generate(prompt: str) -> dict | None:
    """
    プロンプトを Gemini に送り、翌週メニュー＋フィードバックを dict で返す。
    失敗時は None を返す。
    """
    key = _api_key()
    if not key:
        print('[coach_llm] GEMINI_API_KEY が未設定です', file=sys.stderr)
        return None

    model = (os.environ.get('GEMINI_MODEL') or 'gemini-2.5-flash').strip()

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print('[coach_llm] google-genai が未インストールです: pip install google-genai',
              file=sys.stderr)
        return None

    client = genai.Client(api_key=key)
    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM,
                response_mime_type='application/json',
                response_json_schema=_SCHEMA,
                temperature=0.7,
            ),
        )
    except Exception as e:
        print(f'[coach_llm] Gemini API エラー: {e}', file=sys.stderr)
        return None

    raw = (response.text or '').strip()
    if not raw:
        print('[coach_llm] 空レスポンス', file=sys.stderr)
        return None

    result = _parse_json(raw)
    if result is None:
        return None

    # 最低限のバリデーション
    if not all(k in result for k in ('coach_message', 'weekly_plan', 'feedback')):
        print('[coach_llm] レスポンスに必須キーが不足しています', file=sys.stderr)
        return None

    print('[coach_llm] Gemini でメニュー・フィードバックを生成しました', file=sys.stderr)
    return result


if __name__ == '__main__':
    # 単体テスト用（環境変数 GEMINI_API_KEY が必要）
    test_prompt = '''# 筋トレデータ分析レポート

## 直近4週のトレーニング頻度・ボリューム
- 2026-04-27 〜 2026-05-03: 2回 ／ 総ボリューム 3,400 kg

## 主要種目の最高重量推移（直近5セッション）
- ベンチプレス: 80.0kg(05-01)  PB:80.0kg
- スクワット: 90.0kg(04-27)  PB:90.0kg

## 直近2週のRPE平均
- スクワット: 3.0 ⚠ 負荷過多の可能性
- ベンチプレス: 2.0

## 長期目標の進捗
- [max_weight] ベンチプレス: 現在:80.0 / 目標:100.0 (残り20.0)  期限:2026-12-31'''

    result = generate(test_prompt)
    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print('生成失敗（API キーを確認してください）')
