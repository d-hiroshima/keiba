# keiba — 競馬予想エージェントチーム

中央競馬（JRA）の重賞・条件戦を対象とする個人予想支援。`d-hiroshima/kabu`（株式投資分析）と同等の構成で、**5 体のサブエージェント** が血統・コース・展開・直前情報・反証の各観点から議論し、確証バイアスを抑えた予想を生成する。

> ⚠️ **本ツールは賭博助言ではありません。** データの遅延・欠損もあり、最終判断は必ず自己責任で行ってください。

---

## 二系統運用

| 形態 | 用途 | コスト感 |
| --- | --- | --- |
| **A. Claude Code + Remote Control** | 自宅 PC 起動 → スマホ Claude アプリから接続。出先で `/analyze` `/debate` `/recommend` | Pro/Max プラン |
| **B. Slack bot（Cloud Run 常駐）** | 土曜朝の重賞バッチ予想、PC オフでも動く | Anthropic API + Cloud Run |

両方が `.claude/agents/*.md` の system prompt を共有。詳細は [docs/design.md](docs/design.md)。

---

## クイックスタート（A）

```bash
# 1. 依存をインストール（WSL 等で venv を使わない場合）
pip3 install --user --break-system-packages -r requirements.txt
#    venv 派: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# 2. DB 初期化
python3 scripts/db.py

# 3. 分析したいレースを都度指定して取得（watchlist は廃止）
#    （race_id は keibalab の DB URL /db/race/<race_id>/ から。日付ベース YYYYMMDD+場+R）
python3 scripts/fetch_races.py 202605030811

# 4. Claude Code を開いて分析
claude
> /analyze 202605030811
```

### Remote Control（モバイルから接続）

自宅 PC 上で：

```bash
# v2.1.110 以降の Claude Code で
claude --remote-control
# または対話セッション内で /remote-control
```

iOS/Android の Claude アプリから接続して `/recommend` 等を投げる。詳細：<https://code.claude.com/docs/en/remote-control>

---

## クイックスタート（B）

```bash
cd slack-bot
cp .env.example .env       # ANTHROPIC_API_KEY / SLACK_* を設定
pip install -r requirements.txt
python app.py              # ローカル起動（Socket Mode）
```

Cloud Run へのデプロイは `slack-bot/deploy/` 参照。土曜朝の重賞バッチ予想は GitHub Actions（`.github/workflows/`）から CRON 起動。

---

## コマンド一覧

| コマンド | 説明 |
| --- | --- |
| `/analyze <race-id>` | 個別レースの多視点予想（軽量: `pedigree` + `macro-scout` + `critic`） |
| `/analyze <race-id> --full` | 5 エージェント全員召集 |
| `/analyze --horse <horse-id>` | 注目馬の適性・次走分析 |
| `/debate <race-id>` | Agent Teams で多視点議論（重要レース、コスト×3-5） |
| `/recommend` | 当日／週末の「買うべきレース」Top 3-5 提案 |
| `/recommend --budget=3000 --type=wide --points=6` | ワイド予算戦略付き |
| `/update-races <race_id>...` | 指定したレース／馬のデータ最新化 |
| `/review-race <race_id>` | 終了レースの予想を機械採点し、教訓を postmortem に記録 |

---

## エージェント

| Agent | 役割 |
|---|---|
| `pedigree-analyst` | 血統・産駒傾向・配合適性 |
| `track-analyst` | コース適性・距離・脚質・馬場状態 |
| `race-context-analyst` | レースグレード・出走馬レベル・ペース予想・展開 |
| `devils-advocate` | **反対役・穴党・毎回必須** |
| `macro-scout` | 天候・馬場・調教師コメント・直前情報（WebFetch） |

---

## ディレクトリ構成

```
keiba/
├── CLAUDE.md                          # Claude Code 用ルール
├── .claude/                           # === A の本体 ===
│   ├── agents/         # 5 エージェント定義
│   ├── skills/         # 分析手順
│   ├── commands/       # スラッシュコマンド
│   └── settings.json   # CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
├── docs/
│   ├── design.md                      # 初期設計（歴史資料。現行の正は CLAUDE.md）
│   ├── output-schema.md               # 全エージェント出力の必須スキーマ（正）
│   ├── db-schema.md                   # DB スキーマ＋検証済み SQL 例（自動生成）
│   ├── data-policy.md                 # コミット可否のデータ分類
│   ├── postmortems/                   # 外したレースの教訓（反映先チェックリスト付き）
│   └── playbooks/                     # === A・B 共用 ===（コース別 7 本＋汎用 4 本）
├── predictions/                       # 予想の確定保存（発走前 commit = 確定）
├── scripts/                           # === A・B 共用のデータ層 ===
│   ├── db.py                          # スキーマ＋クエリ CLI（card / history / schema-doc）
│   ├── keibalab.py                    # HTTP・キャッシュ・パース集約
│   ├── fetch_races.py                 # 出走表（発走前=馬柱 / 確定後=結果ページ）
│   ├── fetch_results.py               # 結果・戦績・払戻
│   ├── fetch_pedigree.py              # 血統＋産駒成績ローカル集計
│   ├── score_prediction.py            # 予想の機械採点
│   ├── validate_output.py             # 出力スキーマ検証
│   └── import_jravan_csv.py           # JRA-VAN CSV 取り込み（スタブ）
├── tests/                             # パーサ回帰テスト（合成フィクスチャ）
├── data/race.db                       # gitignore
├── slack-bot/                         # === B の本体 ===
│   ├── app.py
│   ├── orchestrator.py
│   ├── agents/
│   ├── prompts/load_agent_prompt.py   # .claude/agents/*.md を読み込み
│   └── deploy/
└── .github/workflows/
    ├── ci.yml                         # lint + pytest + スキーマドリフト検査
    ├── deploy-slack-bot.yml
    └── update-races.yml               # 手動 dispatch でデータ取得 → cache 蓄積 + artifact
```

---

## データソース

主：**keibalab.jp スクレイピング**（`scripts/keibalab.py`。無料・`/db/` robots 許可・低レート・個人利用・非再配布）
併用パス：**JRA-VAN Data Lab**（有料。`scripts/import_jravan_csv.py` は現状スタブ — 初回 CSV 取得時にマッピング実装）
直前情報：macro-scout が公開ニュース・天気サイトを WebFetch（キャッシュなし）
コミット可否の分類は `docs/data-policy.md` を参照（生 HTML・DB・keibalab 指数はコミット禁止）

---

## 開発フェーズ

- **Phase 1**: A の MVP — `pedigree-analyst` + `devils-advocate` で `/analyze` を動かす
- **Phase 2**: A の拡充 — 5 エージェント揃え、`/debate` `/recommend` 実装
- **Phase 3**: B の MVP — Slack bot を Cloud Run にデプロイ
- **Phase 4**: B の運用化 — 土曜朝バッチ、ワイド予算最適化

詳細は [docs/design.md](docs/design.md) の §11。

---

## ライセンスと免責

- 本リポジトリは個人利用範囲。netkeiba 等のスクレイピングデータは再配布しない
- 出力は **賭博助言ではない**。期待値の高い買い目を提示するが、的中保証はない
- データ・プレイブックは陳腐化するため、定期レビューが必須
