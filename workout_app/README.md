# 筋トレ記録アプリ

ブラウザで動作する筋トレトラッキング SPA です。データは **localStorage** に保存されるため、サーバー不要で使えます。

## 使い方

```
workout_app/index.html をブラウザで開く
```

---

## 機能一覧

| タブ | 機能 |
|------|------|
| **メニュー** | コーチからの週間推奨メニューを表示・日別の目標と実績を比較・フィードバック確認 |
| **記録** | 日付ナビゲーション / トレーニング追加・編集・削除 / 種目・セットの管理 |
| **履歴** | カレンダー / 部位別種目一覧 / 種目別の重量推移チャート |

### ワークアウトの記録

1. 「記録」タブで日付を選択
2. 「＋ トレーニングを追加」をタップ
3. **種別選択** → **「＋ 種目を追加」** でエクササイズを選択
4. 各種目のセット数・重量・回数を入力
5. 「保存」

---

## コーチ AI 機能（Python + Gemini）

`workout_pipeline/coach_workout.py` を使うと、Gemini AI が週間メニューとフィードバックを自動生成します。

### セットアップ

```bash
export GEMINI_API_KEY="AIza..."
```

### 1. ワークアウトデータをエクスポート

アプリ右上の ⚙️ → **「ワークアウトデータをエクスポート」** → `workouts.json` を保存

### 2. 週間メニューを生成

```bash
cd workout_pipeline
python coach_workout.py generate-menu \
  --workouts workouts.json \
  --output coach_plan.json
```

### 3. フィードバックを生成（当日トレーニング後）

```bash
python coach_workout.py generate-feedback \
  --workouts workouts.json \
  --plan coach_plan.json \
  --date 2026-05-01 \
  --output coach_plan.json
```

### 4. メニューをアプリにインポート

⚙️ → **「週間メニューをインポート（JSON）」** → `coach_plan.json` を選択

---

### アプリ内 AI 生成（APIキー直接入力）

⚙️ 設定画面で Gemini API キーを登録すると、アプリ内の「✨ AI生成」ボタンから直接メニューを生成できます。

---

## データ構造

アプリが localStorage に保存する JSON のキー：`workout_app_v1`

```json
{
  "workouts": {
    "YYYY-MM-DD": {
      "type": "胸・肩・三頭筋",
      "duration": 68,
      "exercises": [
        {
          "id": "uuid",
          "name": "ベンチプレス",
          "muscle": "胸",
          "isSeconds": false,
          "sets": [
            { "id": "uuid", "w": 80, "r": 10 }
          ]
        }
      ],
      "memo": "",
      "updatedAt": "ISO datetime"
    }
  },
  "weeklyPlan": { ... },
  "settings": {
    "geminiApiKey": "",
    "coachName": "田中コーチ"
  }
}
```

## 週間プラン JSON フォーマット（コーチ側で作成）

```json
{
  "weekStart": "2026-04-27",
  "weekEnd":   "2026-05-03",
  "sentDate":  "2026-04-27",
  "coachMessage": "今週のメッセージ...",
  "days": {
    "2026-04-28": {
      "type": "背中・二頭筋",
      "targets": [
        { "name": "デッドリフト", "sets": 4, "reps": "5", "weight": "100 kg", "note": "フォーム注意" }
      ]
    }
  },
  "feedbacks": {
    "2026-04-28": {
      "text": "フィードバック文...",
      "rating": 5,
      "points": [
        { "type": "positive", "text": "良かった点" },
        { "type": "improve",  "text": "改善点" }
      ],
      "sentAt": "4/28 21:30"
    }
  }
}
```
