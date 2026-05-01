# daily-log-report

Google スプレッドシートの日次ログを自動集計し、**週間・月間・年間レポートを HTML で生成**して GitHub Pages で公開するパイプラインです。

---

## 🗂️ プロジェクト構成

```
daily-log-report/
├── report_pipeline/            # メインのPythonコード
│   ├── generate_week_report.py # HTML生成のエントリーポイント
│   ├── week_aggregate.py       # 週次・月次・年次の集計ロジック
│   ├── daily_log.py            # スプレッドシートのデータ読み込み
│   ├── fetch_daily_log.py      # Google Sheets API 取得
│   ├── coach_comments.py       # コーチコメント（ルールベース）
│   ├── coach_llm_gemini.py     # コーチコメント（Gemini AI）
│   ├── requirements.txt        # 必要なPythonライブラリ
│   └── templates/
│       └── week_report.html.j2 # HTMLテンプレート（Jinja2）
├── .github/
│   └── workflows/
│       └── deploy-report-pages.yml  # GitHub Actions 自動デプロイ
├── report-mockup.html          # UIデザインのモックアップ
└── README.md
```

---

## ⚙️ 動作の仕組み

```
Google スプレッドシート（DailyLog）
        ↓  Google Sheets API で取得
  Python スクリプト（report_pipeline/）
        ↓  週・月・年ごとに集計
  HTML レポート生成（Jinja2 テンプレート）
        ↓  GitHub Actions が毎日自動実行
  GitHub Pages で公開
```

---

## 📊 レポートの内容

| タブ | 表示内容 |
|------|----------|
| **週間** | 日別達成タイル・KPI・コーチコメント・勉強/体重/ランニングチャート |
| **月間** | 週別達成率・月間KPI・コーチコメント・週単位チャート |
| **年間** | 月別達成率・年間KPI・コーチコメント・月単位チャート |

### 追跡カテゴリ
- **学習**（Duolingo・中国語・プログラミング・ドリル）
- **運動**（ランニング km・ペース）
- **健康**（体重 kg）

### コーチ陣
5名からランダムで2名が毎回コメント。Gemini API キーがあれば AI 生成、なければルールベースで自動生成。

| キャラ | 特徴 |
|--------|------|
| 内村さん | 伴走・全肯定・丁寧語 |
| ホタル | データ分析・脱力系 |
| むぎちゃ＆おこげ | 愛犬コンビ・癒やし |
| 老師 | 教訓・長期視点 |
| 修造コーチ | 熱血・全力応援 |

---

## 🚀 セットアップ

### 1. 必要な環境
- Python 3.12 以上
- Google Cloud プロジェクト（サービスアカウント）
- Google Sheets API が有効になっていること

### 2. GitHub Secrets の設定

リポジトリの **Settings → Secrets and variables → Actions** で以下を登録：

| Secret 名 | 内容 |
|-----------|------|
| `GOOGLE_SHEETS_SPREADSHEET_ID` | スプレッドシートの ID（URL の中の長い文字列） |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | サービスアカウントの JSON キー（全文） |
| `GEMINI_API_KEY` | （任意）Google AI Studio の API キー |

### 3. GitHub Pages の設定

**Settings → Pages → Build and deployment → Source** を「GitHub Actions」に変更。

### 4. ローカルで動かす場合

```bash
cd report_pipeline
pip install -r requirements.txt
export GOOGLE_SHEETS_SPREADSHEET_ID="your-spreadsheet-id"
export GOOGLE_APPLICATION_CREDENTIALS="credentials.json"
python generate_week_report.py -o out/index.html
```

---

## 🤖 自動実行スケジュール

| トリガー | タイミング |
|----------|------------|
| **スケジュール** | 毎日 17:00 UTC（中国時間 翌日 01:00） |
| **push 時** | `report_pipeline/` または `.github/workflows/` を変更した場合 |
| **手動** | Actions タブ → 「Run workflow」 |

---

## 📋 スプレッドシートのフォーマット（DailyLog シート）

| 列名 | 内容 | 例 |
|------|------|----|
| `date` | 日付 | `2026/4/1` |
| `category` | カテゴリ | `学習` / `運動` / `健康` |
| `item` | 項目名 | `Duolingo` / `ランニング` / `体重` |
| `unit` | 単位 | `分` / `時間` / `km` / `kg` |
| `value` | 数値 | `65` |
| `note_pace` | ペースメモ（ランニング用） | `5:42` |

---

## 📅 週の仕様

- **週の始まり**: 月曜日（Asia/Shanghai タイムゾーン）
- **月曜日の特例**: 直前に終わった週（先週月〜日）を表示
- **達成判定**: 学習・運動・健康の3カテゴリ全て記録した日を「フル達成（🍺）」とする
