"""
筋トレログを分析して AI へのプロンプトを生成する
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date, timedelta


# ── セッション集約 ────────────────────────────────────────

def group_by_session(records: list[dict]) -> dict[str, dict]:
    """日付ごとにセッション情報をまとめる"""
    sessions: dict[str, dict] = {}

    for r in records:
        d = r['date']
        if d not in sessions:
            sessions[d] = {
                'workout_type': r['workout_type'],
                'duration':     r['duration'],
                'memo':         '',
                'exercises':    defaultdict(list),
            }
        if r['memo']:
            sessions[d]['memo'] = r['memo']
        sessions[d]['exercises'][r['exercise_name']].append(r)

    return dict(sorted(sessions.items()))


# ── 計算ヘルパー ──────────────────────────────────────────

def _session_volume(session: dict) -> float:
    total = 0.0
    for sets in session['exercises'].values():
        for s in sets:
            if s['weight'] and s['reps'] and not s['is_seconds']:
                total += s['weight'] * s['reps']
    return total


def _max_weight(sets: list[dict]) -> float | None:
    weights = [s['weight'] for s in sets if s['weight'] and not s['is_seconds']]
    return max(weights) if weights else None


def _week_range(week_offset: int = 0):
    """week_offset=0: 今週、1: 先週、..."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    ws = monday - timedelta(weeks=week_offset)
    we = ws + timedelta(days=6)
    return ws.isoformat(), we.isoformat()


# ── メイン分析 ────────────────────────────────────────────

def analyze(records: list[dict], goals: list[dict]) -> dict:
    """
    全レコードを受け取り、分析結果を dict で返す。
    """
    sessions = group_by_session(records)

    # ── 直近4週の頻度・ボリューム ──────────────────────────
    weeks = []
    for offset in range(4):
        ws, we = _week_range(offset)
        week_sessions = {d: s for d, s in sessions.items() if ws <= d <= we}
        weeks.append({
            'week_start':    ws,
            'week_end':      we,
            'session_count': len(week_sessions),
            'total_volume':  sum(_session_volume(s) for s in week_sessions.values()),
            'workout_types': [s['workout_type'] for s in week_sessions.values()],
        })

    # ── 種目別重量推移（全期間） ───────────────────────────
    exercise_progress: dict[str, list[dict]] = defaultdict(list)
    for d, session in sorted(sessions.items()):
        for ex_name, sets in session['exercises'].items():
            mw = _max_weight(sets)
            if mw:
                exercise_progress[ex_name].append({'date': d, 'max_weight': mw})

    # ── 種目別 PB（自己ベスト） ────────────────────────────
    pb: dict[str, float] = {
        ex: max(h['max_weight'] for h in history)
        for ex, history in exercise_progress.items()
        if history
    }

    # ── 直近2週の RPE 平均 ────────────────────────────────
    two_weeks_ago = (date.today() - timedelta(weeks=2)).isoformat()
    rpe_by_ex: dict[str, list[int]] = defaultdict(list)
    for r in records:
        if r['date'] >= two_weeks_ago and r['rpe']:
            rpe_by_ex[r['exercise_name']].append(r['rpe'])
    rpe_avg = {ex: sum(v) / len(v) for ex, v in rpe_by_ex.items() if v}

    # ── 目標進捗 ──────────────────────────────────────────
    goal_progress = []
    for g in goals:
        entry = dict(g)
        if g['exercise_name'] and g['goal_type'] == 'max_weight':
            history = exercise_progress.get(g['exercise_name'], [])
            entry['current_value'] = history[-1]['max_weight'] if history else None
        elif g['goal_type'] == 'weekly_sessions':
            entry['current_value'] = weeks[0]['session_count']  # 今週の実績
        else:
            entry['current_value'] = None
        goal_progress.append(entry)

    return {
        'weeks':             weeks,
        'exercise_progress': dict(exercise_progress),
        'pb':                pb,
        'rpe_avg':           rpe_avg,
        'goal_progress':     goal_progress,
        'recent_sessions':   dict(list(sorted(sessions.items()))[-5:]),  # 直近5セッション
    }


# ── AI プロンプト生成 ─────────────────────────────────────

def build_prompt(analysis: dict) -> str:
    """Gemini に渡すプロンプト文字列を生成する"""

    weeks    = analysis['weeks']
    progress = analysis['exercise_progress']
    rpe_avg  = analysis['rpe_avg']
    goals    = analysis['goal_progress']
    pb       = analysis['pb']

    lines = ['# 筋トレデータ分析レポート', '']

    # 直近4週の頻度・ボリューム
    lines += ['## 直近4週のトレーニング頻度・ボリューム']
    for w in weeks:
        vol = f"{w['total_volume']:,.0f} kg" if w['total_volume'] else '記録なし'
        lines.append(
            f"- {w['week_start']} 〜 {w['week_end']}: "
            f"{w['session_count']} 回 ／ 総ボリューム {vol}"
        )
    lines.append('')

    # 種目別重量推移（直近5セッション）
    lines += ['## 主要種目の最高重量推移（直近5セッション）']
    for ex, history in sorted(progress.items()):
        recent = history[-5:]
        trend  = ' → '.join(f"{h['max_weight']}kg({h['date'][5:]})" for h in recent)
        pb_str = f"PB:{pb[ex]}kg" if ex in pb else ''
        lines.append(f"- {ex}: {trend}  {pb_str}")
    lines.append('')

    # RPE傾向
    lines += ['## 直近2週のRPE平均（1=余裕あり / 2=きつい / 3=限界）']
    if rpe_avg:
        for ex, avg in sorted(rpe_avg.items(), key=lambda x: -x[1]):
            alert = ' ⚠ 負荷過多の可能性' if avg >= 2.5 else ''
            lines.append(f"- {ex}: {avg:.1f}{alert}")
    else:
        lines.append('- データなし')
    lines.append('')

    # 長期目標進捗
    if goals:
        lines += ['## 長期目標の進捗']
        for g in goals:
            ex_label = g['exercise_name'] or '全体'
            target   = f"{g['target_value']} {g['unit']}" if g['target_value'] else '―'
            deadline = f"期限:{g['target_date']}" if g['target_date'] else ''
            current  = g.get('current_value')
            if current is not None and g['target_value']:
                diff = g['target_value'] - current
                progress_str = f"現在:{current} / 目標:{g['target_value']} (残り{diff:.1f})"
            else:
                progress_str = target
            lines.append(f"- [{g['goal_type']}] {ex_label}: {progress_str}  {deadline}")
        lines.append('')

    # AI への指示
    lines += [
        '## 指示',
        '上記データをもとに、以下のJSON形式で翌週プランとフィードバックを出力してください。',
        '',
        '```json',
        '{',
        '  "coach_message": "週全体へのコーチメッセージ（200〜300字）",',
        '  "weekly_plan": [',
        '    {',
        '      "training_date": "YYYY-MM-DD",',
        '      "workout_type": "胸・肩・三頭筋",',
        '      "exercises": [',
        '        {',
        '          "name": "種目名",',
        '          "target_sets": 4,',
        '          "target_reps": "8-10",',
        '          "target_weight": "80 kg",',
        '          "coach_note": "種目ごとの根拠つき指示（50〜100字）"',
        '        }',
        '      ]',
        '    }',
        '  ],',
        '  "feedback": {',
        '    "rating": 4,',
        '    "text": "直近トレーニングへのフィードバック（150〜250字）",',
        '    "points": [',
        '      {"type": "positive", "text": "良かった点"},',
        '      {"type": "improve",  "text": "改善点"}',
        '    ]',
        '  }',
        '}',
        '```',
        '',
        '条件:',
        '- 漸進性過負荷の原則に基づき、前回比+2.5〜5kgまたは+1〜2repを目安に設定すること',
        '- RPE平均が2.5以上の種目は重量を据え置きまたは減量を検討すること',
        '- 長期目標の達成から逆算した週次目標を設定すること',
        '- 翌週（月曜〜日曜）のメニューを作成すること',
        '- JSON以外のテキストは出力しないこと',
    ]

    return '\n'.join(lines)


if __name__ == '__main__':
    from fetch_workout_log import fetch_workout_log, fetch_goals

    records  = fetch_workout_log()
    goals    = fetch_goals()
    result   = analyze(records, goals)
    prompt   = build_prompt(result)
    print(prompt)
