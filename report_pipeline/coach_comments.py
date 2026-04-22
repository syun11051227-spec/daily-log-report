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

import random

# レポートに表示する人数（全5人のうちランダムに選ぶ）
COACH_DISPLAY_COUNT = 2

# Cursor / LLM 用・コーチ陣の振る舞いメモ（貼り付け用）
COACH_LLM_RULES_SNIPPET = """
コーチ陣の振る舞いについて：
- 各コーチは、ユーザーの「プログラミング（VS Code/Cursor）」「中国語（Duolingo）」「ランニング（5km/5:42ペース）」「体重管理」の進捗に基づいてコメントを生成してください。
- 1（内村）は心理的安全性を確保し、2（ホタル）はデータ分析と脱力感を与え、3（むぎこげ）はひたすら癒やし、4（老師）は長期的視点を与え、5（修造）は熱量で背中を押すこと。
- 特に2匹の愛犬の鳴き声（むぎむー、こげげー）は忠実に再現してください。
""".strip()

from dataclasses import dataclass
from typing import NamedTuple

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


def _tile_kind_counts(rep: WeekReport) -> tuple[int, int, int]:
    """部分達成・未・フルの日数。"""
    partial = empty = full = 0
    for t in rep.tiles:
        if t.kind == "partial":
            partial += 1
        elif t.kind == "empty":
            empty += 1
        else:
            full += 1
    return partial, empty, full


def _run_total_km(rep: WeekReport) -> float:
    return float(sum(rep.run_km_by_day))


class _CoachSignals(NamedTuple):
    totals: dict[str, float]
    study_sum: float
    days_study_goal: int
    run_goal_days: int
    run_total_km: float
    partial_days: int
    empty_days: int
    full_days: int
    top_item: str | None
    wdelta: float | None
    pace_avg: float | None
    pace_goal: float | None
    pace_beat_goal: bool
    duo: float
    cn: float
    prog: float
    drill: float


def _signals(rep: WeekReport) -> _CoachSignals:
    totals = _study_totals(rep)
    study_sum = sum(totals.values())
    partial, empty, full = _tile_kind_counts(rep)
    top = _top_study_item(totals)
    wdelta = _weight_delta_kg(rep)
    pace_avg = _pace_avg_min(rep)
    pace_goal = _pace_goal_min(rep)
    pace_beat = (
        pace_avg is not None
        and pace_goal is not None
        and pace_avg < pace_goal - 0.01
    )
    return _CoachSignals(
        totals=totals,
        study_sum=study_sum,
        days_study_goal=_days_meeting_study_goal(rep),
        run_goal_days=_run_days_at_goal(rep),
        run_total_km=_run_total_km(rep),
        partial_days=partial,
        empty_days=empty,
        full_days=full,
        top_item=top,
        wdelta=wdelta,
        pace_avg=pace_avg,
        pace_goal=pace_goal,
        pace_beat_goal=pace_beat,
        duo=float(totals.get("Duolingo", 0.0)),
        cn=float(totals.get("中国語", 0.0)),
        prog=float(totals.get("プログラミング", 0.0)),
        drill=float(totals.get("ドリル", 0.0)),
    )


def build_coach_cards(rep: WeekReport) -> list[CoachCard]:
    z = _signals(rep)

    # --- 1 内村（丁寧語・全肯定・数字はさりげなく）---
    if rep.week_full_days >= 7:
        u1 = f"「7日ともフル達成ですねぇ。{rep.week_rate}%の週、立派すぎます。」"
    elif rep.week_rate >= 85:
        u1 = f"「この週、達成率{rep.week_rate}%ですねぇ。素晴らしいなぁ。」"
    elif rep.week_rate >= 50:
        u1 = f"「週{rep.week_rate}%、着実に積み上がっていますねぇ。」"
    elif rep.week_rate > 0:
        if z.partial_days > 0:
            u1 = f"「今週は{rep.week_rate}%でしたねぇ。★の日が{z.partial_days}日ありますねぇ。芽はちゃんと出ています。」"
        else:
            u1 = f"「今週は{rep.week_rate}%でしたねぇ。そういう週もあります。小さな一歩、拾えていれば十分です。」"
    else:
        u1 = "「記録が少なめの週でしたねぇ。体調や予定の波もあります。無理せず行きましょう。」"

    if rep.prev_rate < rep.week_rate and rep.week_rate > 0:
        u2 = f"「先週{rep.prev_rate}%から今週{rep.week_rate}%ですねぇ。少しずつ形になっています。」"
    elif rep.streak_any_input >= 14:
        u2 = f"「連続{rep.streak_any_input}日、手帳に触れていますねぇ。続けること自体が、もう才能です。」"
    elif rep.streak_any_input >= 7:
        u2 = f"「連続{rep.streak_any_input}日、何かしら手を付けていますねぇ。続いていることが何よりです。」"
    elif rep.streak_any_input >= 3:
        u2 = f"「連続{rep.streak_any_input}日の入力、えらいですよ。」"
    elif z.empty_days >= 5:
        u2 = "「空白の日が多くても、責めないでくださいねぇ。次の一歩だけ、見えれば十分です。」"
    else:
        u2 = "「また来週も、こちらでお待ちしていますねぇ。」"

    uchan = CoachCard(
        slug="uchan",
        name="内村さん",
        role="伴走のリーダー · メンタル維持",
        lines=(u1, u2),
    )

    # --- 2 ホタル（明るく・データ＋脱力）---
    if z.study_sum >= GOAL_STUDY_MIN_PER_DAY * 5:
        h1 = f"「データ、完璧です！週合計{int(z.study_sum)}分…え、私より働いてる。尊敬です〜。」"
    elif z.study_sum > 0:
        h1 = f"「勉強ログ、合計{int(z.study_sum)}分。Duolingo{z.duo:.0f}分・中国語{z.cn:.0f}分・コード{z.prog:.0f}分…几帳面さん、尊敬しちゃいます。」"
    else:
        h1 = "「勉強ゼロ週…まあ、ビール飲んでゴロゴロした〜い日も必要ですよね。」"

    if z.run_goal_days >= 1 and z.study_sum > 0:
        h2 = f"「ラン{z.run_goal_days}日が5km超え＆勉強も{int(z.study_sum)}分。データ上は優等生〜。…あたしは帰ります。」"
    elif z.partial_days >= 3:
        h2 = f"「★部分達成が{z.partial_days}日。フルまであと一息、って感じですね〜。」"
    elif z.top_item and z.totals.get(z.top_item, 0) > 0 and z.study_sum > 0:
        share = 100.0 * z.totals[z.top_item] / z.study_sum
        h2 = f"「{z.top_item}がトップで全体の約{share:.0f}%。分析はここまで。あとは私、サボります。」"
    else:
        h2 = "「次は入力だけポチッと。それだけでトレンド線、動きます。」"

    hotaru = CoachCard(
        slug="hotaru",
        name="ホタル",
        role="脱力系アナリスト",
        lines=(h1, h2),
    )

    # --- 3 むぎ＆こげ（鳴き声＋括弧で状況）---
    if rep.week_full_days >= 5:
        tail = "（フルばっかり！しっぽブンブン！おやつも忘れないでね！）"
    elif rep.week_full_days >= 1:
        tail = f"（★の日も{z.partial_days}日あるよ。おうちでずっと待ってた！）"
    elif z.streak_any_input >= 1:
        tail = f"（連続{z.streak_any_input}日なにか書いてるの、すごい！むぎむー！）"
    else:
        tail = "（記録少なくても大好き！むぎもこげも応援してる！）"
    mugi = CoachCard(
        slug="mugikoge",
        name="むぎちゃ ＆ おこげ",
        role="癒やしの家族",
        lines=("「むぎむー！」「こげげー！」", tail),
    )

    # --- 4 老師（教訓・語学/程序・体重）---
    if z.prog > z.cn and z.prog > z.duo and z.prog > 10:
        l1 = "「程序に時間を割けていますな。タイヤのように、一層ずつ削れて形になります。」"
    elif z.cn + z.duo > z.prog and z.cn + z.duo > 10:
        l1 = "「語学の積み上げ、目に見えますな。耳と口は、工場のラインと同じで、回せば慣れる。」"
    else:
        l1 = "「千里の道も一歩からですな。語学も程序も、現場のタイヤも、積み重ねがいちばん正直です。」"

    if z.days_study_goal >= 3:
        l2 = f"「60分超えの日が{z.days_study_goal}日。着実ですな。」"
    elif z.study_sum > 0:
        l2 = f"「週{int(z.study_sum)}分。少しずつでよい。心で感じなさい、今日の積み分。」"
    else:
        l2 = "「風の向きが変わることもある。次の一歩だけ、考えればよいですな。」"

    if z.run_total_km > 0 and z.run_goal_days == 0:
        l3 = f"「走行距離は週で{z.run_total_km:.1f} km。距離は積めていますな。次はペースを育てましょう。」"
    elif z.wdelta is not None:
        if z.wdelta < -0.05:
            l3 = f"「体重、週では{z.wdelta:+.1f} kg。減り方に体は正直ですな。」"
        elif z.wdelta > 0.05:
            l3 = f"「体重{z.wdelta:+.1f} kg。水分や塩分もありますな。長い目で。」"
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

    # --- 5 修造（高温・比喩）---
    if z.pace_beat_goal and z.run_goal_days >= 1:
        s1 = "「おい！ペース、目標より速い！お前はタイヤだ！地面を食って進め！」"
    elif z.run_goal_days >= 3:
        s1 = f"「{z.run_goal_days}日、5 km超え！できる！できる！心は快晴だ！」"
    elif z.run_goal_days >= 1:
        s1 = "「走れた日がある！それが勝ちだ！おめでとう！」"
    elif z.run_total_km > 0:
        s1 = f"「週で{z.run_total_km:.1f} km、脚は動いてる！次は5kmで景色が変わる、熱くなれよ！」"
    else:
        s1 = "「脚はまだ火を帯びている！次、一発出せ！熱くなれよ！」"

    if rep.pace_avg_min_per_km and not z.pace_beat_goal and z.run_goal_days >= 1:
        s2 = f"「平均ペース{rep.pace_avg_min_per_km}/km、まだ伸びしろだ！タイムはライバルじゃない、仲間だ！」"
    elif rep.week_full_days >= 4:
        s2 = "「週のフル達成、こんなに積んだか！限界、まだ先だ！」"
    elif z.study_sum >= GOAL_STUDY_MIN_PER_DAY * 4:
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


def pick_coach_cards_for_display(
    all_cards: list[CoachCard],
    count: int = COACH_DISPLAY_COUNT,
) -> list[CoachCard]:
    """全コーチの文を用意したうえで、count 名だけ重複なくランダム表示用に選ぶ。

    表示順は build_coach_cards の定義順（内村→ホタル→むぎこげ→老師→修造）に揃える。
    """
    if len(all_cards) <= count:
        return list(all_cards)
    order = {c.slug: i for i, c in enumerate(all_cards)}
    picked = random.sample(all_cards, count)
    picked.sort(key=lambda c: order[c.slug])
    return picked
