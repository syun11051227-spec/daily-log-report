"""週次レポート用・5コーチのルールベース短コメント（外部 API なし）。

キャラ定義（口調の目安）:
  1 内村さん … 伴走・全肯定・丁寧語「〜ですねぇ」
  2 ホタル … 分析＋脱力「データ完璧！」系
  3 むぎちゃ＆おこげ … むぎむー／こげげー＋（）で代弁
  4 老師 … 教訓調「〜ですな」千里の道 等
  5 修造コーチ … 高温・「熱くなれよ！」比喩

進捗は WeekReport（学習内訳・ラン・体重・達成タイル等）から算出する。

以下は LLM 用システム指示の下書きとしても流用可（本モジュールの build_coach_cards は外部 API 不使用）。
"""

from __future__ import annotations

# Cursor / LLM 用・コーチ陣の振る舞いメモ（貼り付け用）
COACH_LLM_RULES_SNIPPET = """
コーチ陣の振る舞いについて：
- 各コーチは、ユーザーの「プログラミング（VS Code/Cursor）」「中国語（Duolingo）」「ランニング（5km/5:42ペース）」「体重管理」の進捗に基づいてコメントを生成してください。
- 1（内村）は心理的安全性を確保し、2（ホタル）はデータ分析と脱力感を与え、3（むぎこげ）はひたすら癒やし、4（老師）は長期的視点を与え、5（修造）は熱量で背中を押すこと。
- 特に2匹の愛犬の鳴き声（むぎむー、こげげー）は忠実に再現してください。
""".strip()

from dataclasses import dataclass

from week_aggregate import (
    GOAL_RUN_KM_PER_DAY,
    GOAL_STUDY_MIN_PER_DAY,
    STUDY_ITEMS_ORDER,
    WeekReport,
    parse_pace_min_per_km,
)


@dataclass(frozen=True)
class CoachCard:
    """テンプレート向け・1コーチ分。"""

    slug: str
    name: str
    role: str
    lines: tuple[str, ...]


def _study_totals(rep: WeekReport) -> dict[str, float]:
    acc = {k: 0.0 for k in STUDY_ITEMS_ORDER}
    for day in rep.study_by_day:
        for k in STUDY_ITEMS_ORDER:
            acc[k] += float(day.get(k, 0.0) or 0.0)
    return acc


def _days_meeting_study_goal(rep: WeekReport) -> int:
    return sum(1 for d in rep.study_by_day if sum(d.values()) >= GOAL_STUDY_MIN_PER_DAY)


def _run_days_at_goal(rep: WeekReport) -> int:
    return sum(1 for km in rep.run_km_by_day if km >= GOAL_RUN_KM_PER_DAY)


def _pace_avg_min(rep: WeekReport) -> float | None:
    s = rep.pace_avg_min_per_km
    if not s:
        return None
    return parse_pace_min_per_km(s)


def _pace_goal_min(rep: WeekReport) -> float | None:
    return parse_pace_min_per_km(rep.pace_goal_label)


def _weight_delta_kg(rep: WeekReport) -> float | None:
    a, b = rep.weight_labels
    if not a or not b:
        return None
    try:
        return float(b) - float(a)
    except ValueError:
        return None


def _top_study_item(totals: dict[str, float]) -> str | None:
    if not any(totals.values()):
        return None
    return max(totals, key=lambda k: totals[k])


def build_coach_cards(rep: WeekReport) -> list[CoachCard]:
    totals = _study_totals(rep)
    study_sum = sum(totals.values())
    days_study_goal = _days_meeting_study_goal(rep)
    run_goal_days = _run_days_at_goal(rep)
    top_item = _top_study_item(totals)
    wdelta = _weight_delta_kg(rep)
    pace_avg = _pace_avg_min(rep)
    pace_goal = _pace_goal_min(rep)
    pace_beat_goal = (
        pace_avg is not None
        and pace_goal is not None
        and pace_avg < pace_goal - 0.01
    )

    # --- 1 内村 ---
    if rep.week_rate >= 85:
        u1 = f"「この週、達成率{rep.week_rate}%ですねぇ。素晴らしいなぁ。」"
    elif rep.week_rate >= 50:
        u1 = f"「週{rep.week_rate}%、着実に積み上がっていますねぇ。」"
    elif rep.week_rate > 0:
        u1 = f"「今週は{rep.week_rate}%でしたねぇ。そういう週もあります。小さな一歩、拾えていれば十分です。」"
    else:
        u1 = "「記録が少なめの週でしたねぇ。体調や予定の波もあります。無理せず行きましょう。」"
    if rep.streak_any_input >= 7:
        u2 = f"「連続{rep.streak_any_input}日、何かしら手を付けていますねぇ。続いていることが何よりです。」"
    elif rep.streak_any_input >= 3:
        u2 = f"「連続{rep.streak_any_input}日の入力、えらいですよ。」"
    else:
        u2 = "「また来週も、こちらでお待ちしていますねぇ。」"
    uchan = CoachCard(
        slug="uchan",
        name="内村さん",
        role="伴走のリーダー · メンタル維持",
        lines=(u1, u2),
    )

    # --- 2 ホタル ---
    if study_sum >= GOAL_STUDY_MIN_PER_DAY * 5:
        h1 = "「データ、完璧です！…いや週トータル的にはかなり厚みあります。えらすぎ〜。」"
    elif study_sum > 0:
        h1 = f"「勉強ログ、合計{int(study_sum)}分くらい入ってます。几帳面さん、尊敬しちゃいます。」"
    else:
        h1 = "「勉強ゼロ週…まあ、ビール飲んでゴロゴロした〜い日も必要ですよね。」"
    if top_item and totals.get(top_item, 0) > 0:
        h2 = f"「{top_item}が一番多め。分析はここまで。あとは私、サボります。」"
    else:
        h2 = "「次は入力だけポチッと。それだけでトレンド線、動きます。」"
    hotaru = CoachCard(
        slug="hotaru",
        name="ホタル",
        role="脱力系アナリスト",
        lines=(h1, h2),
    )

    # --- 3 むぎ＆こげ ---
    if rep.week_full_days >= 5:
        tail = "（フル達成、いっぱい！しっぽブンブン！）"
    elif rep.week_full_days >= 1:
        tail = "（まあるい一週間、おうちで待ってたよ）"
    else:
        tail = "（記録少なくても大好き！むぎもこげも応援してる！）"
    mugi = CoachCard(
        slug="mugikoge",
        name="むぎちゃ ＆ おこげ",
        role="癒やしの家族",
        lines=("「むぎむー！」「こげげー！」", tail),
    )

    # --- 4 老師 ---
    l1 = "「千里の道も一歩からですな。語学も程序も、現場のタイヤも、積み重ねがいちばん正直です。」"
    if days_study_goal >= 3:
        l2 = f"「勉強目標の日が{days_study_goal}日。着実ですな。」"
    elif study_sum > 0:
        l2 = "「少しずつでよい。心で感じなさい、今日の積み分。」"
    else:
        l2 = "「風の向きが変わることもある。次の一歩だけ、考えればよいですな。」"
    if wdelta is not None:
        if wdelta < -0.05:
            l3 = f"「体重、週の範囲では{wdelta:+.1f} kg。体は覚えていますぞ。」"
        elif wdelta > 0.05:
            l3 = f"「体重{wdelta:+.1f} kg。季節や水分もありますな。長い目で。」"
        else:
            l3 = "「体重は大きく動いていませんな。安定も立派です。」"
    else:
        l3 = "「記録が薄い日は、休むも修行ですな。」"
    laoshi = CoachCard(
        slug="laoshi",
        name="老師",
        role="駐在の賢者",
        lines=(l1, l2, l3),
    )

    # --- 5 修造 ---
    if pace_beat_goal and run_goal_days >= 1:
        s1 = "「おい！ペース、目標より速い！お前はタイヤだ！地面を食って進め！」"
    elif run_goal_days >= 3:
        s1 = f"「{run_goal_days}日、5 km超え！できる！できる！心は快晴だ！」"
    elif run_goal_days >= 1:
        s1 = "「走れた日がある！それが勝ちだ！おめでとう！」"
    else:
        s1 = "「脚はまだ火を帯びている！次、一発出せ！熱くなれよ！」"
    if rep.week_full_days >= 4:
        s2 = "「週のフル達成、こんなに積んだか！限界、まだ先だ！」"
    elif study_sum >= GOAL_STUDY_MIN_PER_DAY * 4:
        s2 = "「勉強の分、ドカンと積んでる！その勢い、持ってけ！」"
    else:
        s2 = "「数字が伸びなくても、挑んだ自分に拍手だ！次、同じ場所で熱くなれ！」"
    shuzo = CoachCard(
        slug="shuzo",
        name="修造コーチ",
        role="太陽の応援団",
        lines=(s1, s2),
    )

    return [uchan, hotaru, mugi, laoshi, shuzo]
