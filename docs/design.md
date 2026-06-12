# keiba プロジェクト設計ドキュメント

> ⚠️ **本文書は 2026-05 時点の初期設計（歴史資料）**。現行の正は `CLAUDE.md` と
> `docs/output-schema.md` / `docs/db-schema.md`。特にデータソースは **keibalab.jp が正**
> （本文中の「netkeiba 第一候補」は初期検討時の記述。経緯は memory: data-source-decision）。
>
> このドキュメントは Claude.ai 上での設計議論の結論をまとめた **handoff ドキュメント** です。
> Claude Code はこのファイルを context として読み、`keiba/` リポジトリの初期構築を進めてください。
> 既存の `d-hiroshima/kabu` リポジトリを雛形として強く参考にすることを前提とします。

---

## 1. 背景と目的

`d-hiroshima/kabu`（株式投資分析の Claude Code 環境）と同等の構成で、**競馬予想用のエージェントチーム環境** を構築したい。kabu 同様に subagent + Agent Teams + プレイブック方式で「確証バイアスを抑えた予想」を実現する。

加えて、**モバイルからも動かしたい** という要件があるため、以下の 2 つの運用形態を **同一リポジトリ内で両立** させる。

---

## 2. 採用した運用方針：A + B 併用

### A. Claude Code + Remote Control（メイン運用、kabu 同型）

- 自宅 PC で Claude Code を起動 (`claude --remote-control` または `/remote-control`)
- iOS/Android の Claude アプリから接続して、出先からスマホで `/recommend` 等を投げる
- Push 通知で長時間タスク完了を受け取る
- **kabu の `.claude/` 構成（agents / skills / commands）がそのまま動く**ので、`/debate`、`/recommend` も問題なく使える
- 制約：
  - PC が起動している必要がある（自宅 Mac/Win を立ち上げっぱなし）
  - 1 セッション 1 接続、約 10 分のネットワーク途切れでタイムアウト
  - Pro/Max プランのみ（research preview）
  - claude.ai アカウントでの認証必須（長期トークンは不可）
- → 普段使い・出先のレース前確認で利用

### B. Slack bot をクラウドで常駐（PC 非依存）

- Python + Slack Bolt（Socket Mode）+ Anthropic API + MCP（以前 Claude に検討してもらった構成、MVP 3〜5 日見積り）
- Cloud Run / Fargate / Render あたりにデプロイ（Socket Mode 常時接続のため Lambda よりこれらが向く）
- 土曜朝 CRON で当日重賞の予想をバッチ生成 → Slack 投稿、もインタラクティブな `/keiba` コマンドも両方サポート
- **Claude Code の Agent Teams（`/debate` のメンバー間 SendMessage）は API では現状そのまま使えない**ため、自前で orchestration ループを実装する
  - lead → pedigree-analyst（並列）→ track-analyst（並列）→ devils-advocate（最後に必須）の流れ
  - kabu の「devils-advocate を毎回最後に通す」思想は B でも維持
- → 週末バッチ・PC オフでも動かしたい用途

### A と B の役割分担

| 用途 | 担当 |
| --- | --- |
| 出先での個別レース予想（インタラクティブ） | A |
| `/debate` のような多視点議論（重要レース） | A |
| 土曜朝の重賞一括バッチ予想 | B |
| 平日の調教・出馬表チェック自動化 | B |
| ワイド戦略の予算最適化（`/recommend --budget=3000`） | A をメインに、B にも実装 |

---

## 3. リポジトリ構成（monorepo 提案）

```
keiba/
├── README.md
├── CLAUDE.md                          # Claude Code 用ルール
├── .claude/                           # === A の本体 ===
│   ├── agents/
│   │   ├── pedigree-analyst.md
│   │   ├── track-analyst.md
│   │   ├── race-context-analyst.md
│   │   ├── devils-advocate.md
│   │   └── macro-scout.md
│   ├── skills/
│   │   ├── analyze-race.md
│   │   ├── recommend-races.md
│   │   └── debate-race.md
│   ├── commands/
│   │   ├── analyze.md
│   │   ├── debate.md
│   │   ├── recommend.md
│   │   └── update-races.md
│   └── settings.json                  # CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
├── docs/
│   ├── design.md                      # ← このファイル
│   └── playbooks/                     # === A・B 共用の重量知識資産 ===
│       ├── _template.md
│       ├── grade-race.md              # GI/GII の傾向、過去事例
│       ├── tokyo-2400.md              # コース別プレイブック
│       ├── nakayama-2500.md
│       ├── kyoto-3200.md
│       ├── pace-analysis.md           # 脚質・ペース予想の枠組み
│       └── wide-strategy.md           # ワイド予算戦略の方法論
├── scripts/                           # === A・B 共用のデータ層 ===
│   ├── db.py                          # SQLite スキーマ
│   ├── fetch_races.py                 # 出走表取得（keibalab。馬柱/結果ページ自動分岐）
│   ├── fetch_results.py               # レース結果取得
│   ├── fetch_pedigree.py              # 血統情報取得
│   └── import_jravan_csv.py           # JRA-VAN Data Lab CSV 取り込み（任意）
├── data/                              # gitignore（kabu と同じ方針）
│   └── race.db
├── slack-bot/                         # === B の本体 ===
│   ├── app.py                         # Slack Bolt エントリポイント
│   ├── orchestrator.py                # 自前 multi-agent オーケストレーション
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── pedigree.py
│   │   ├── track.py
│   │   ├── race_context.py
│   │   ├── devils_advocate.py
│   │   └── macro_scout.py
│   ├── prompts/
│   │   └── load_agent_prompt.py       # .claude/agents/*.md を読み込んで再利用
│   ├── deploy/
│   │   ├── Dockerfile
│   │   └── docker-compose.yml
│   ├── requirements.txt
│   └── README.md
├── requirements.txt                   # A 用（scripts/ から叩く）
└── .github/
    └── workflows/
        ├── deploy-slack-bot.yml       # B のデプロイ
        ├── update-races.yml           # 指定レースのデータ取得（手動 dispatch）→ 自動 PR
        └── ci.yml                     # 共通 lint/test
```

**設計のキモ**：

- `.claude/agents/*.md` の system prompt 本文を、`slack-bot/agents/*.py` から **そのまま読み込んで再利用** する。プロンプトの一元管理により、A で改善したエージェント定義が B にも自動的に反映される。
- `docs/playbooks/` は A・B 両方から参照される「重量知識」。kabu の `docs/playbooks/semis.md` 等と同じ役割。
- `scripts/` で取得したデータは `data/race.db`（SQLite）に貯め、A・B どちらからもクエリ可能にする。

---

## 4. エージェント編成

kabu の 5 エージェント編成を競馬ドメインに翻訳。

| エージェント | 役割 | kabu での対応 | 招集タイミング |
| --- | --- | --- | --- |
| `pedigree-analyst` | 血統・産駒傾向・配合適性 | fundamentals-analyst | デフォルト必須 |
| `track-analyst` | コース適性・距離・脚質・馬場状態 | technical-analyst | コース論点が中心のとき |
| `race-context-analyst` | レースグレード・出走馬レベル・ペース予想・展開 | sector-analyst | 該当レース層のとき |
| `devils-advocate` | 本命崩しの穴党（強気論を要約してから反証） | devils-advocate | **毎回必須・最後に呼ぶ** |
| `macro-scout` | 天候・馬場・調教師コメント・直前情報（WebFetch） | macro-scout | `/recommend` 時に起動 |

**出力フォーマット規約**（kabu と同型、全エージェント必須）：

```
強気度: -5（強い消し） 〜 +5（強い本命）
確信度: 1 〜 5
根拠: 3点
反証条件: "What would change my mind?" 1点
```

---

## 5. 提供コマンド

kabu の 3 モード構成を踏襲。

| コマンド | 説明 | コスト感 |
| --- | --- | --- |
| `/analyze <race-id>` | 個別レースの選抜分析（軽量） | 軽 |
| `/analyze <race-id> --full` | 5 エージェント全員召集 | 中 |
| `/debate <race-id>` | Agent Teams による多視点議論 | 中（×3-5）|
| `/recommend` | 当日／週末の「買うべきレース」Top 3-5 提案 | 重（×5-10）|
| `/recommend --budget=3000 --type=wide` | ワイド予算戦略付き | 重 |
| `/update-races <race_id>...` | 指定したレース／馬のデータ最新化 | 軽 |

ワイド戦略は `--budget` と `--points`（点数）と `--ev-threshold`（期待値しきい値）を引数化。

---

## 6. データソース

> **採用済み（2026-05 決定）: keibalab.jp スクレイピング**（`scripts/keibalab.py`）。
> 以下の「netkeiba 第一候補」は初期検討時の記述として残す。

**初期検討時の第一候補：netkeiba スクレイピング**
- 出走表、過去戦績、血統、調教情報
- 規約・robots.txt の確認必須
- 取得頻度に注意（rate limit）

**第二候補：JRA-VAN Data Lab（有料・公式）**
- 安定性・データ品質は段違い
- 月額費用が発生
- CSV エクスポート → `scripts/import_jravan_csv.py` で取り込み

**直前情報（macro-scout が WebFetch）**
- 馬場状態、天気、調教師・騎手コメント
- 直前情報はキャッシュせず都度取得

---

## 7. プレイブック方針

kabu のプレイブックと同様、`docs/playbooks/` に重量資料を蓄積。各プレイブックには以下を含める：

- 主要 KPI と観察ポイント（コース別の有利不利、距離別の傾向）
- 過去事例（直近 5 年の重賞結果、紛れたレースの分析）
- 強気/弱気シグナル
- バリュエーション手法（オッズと期待値の比較フレーム）
- 主要血統・厩舎の比較表

四半期ごとに最新動向と照合してレビュー。

---

## 8. 技術選定の詳細

### Slack bot のホスティング
- **第一候補：Cloud Run**（Socket Mode 常時接続、コールドスタート許容、課金しやすい）
- 第二候補：Fargate / Render
- Lambda は Socket Mode と相性が悪いので避ける（Events API + HTTP モードに切り替えるなら可）

### GitHub Actions
- `deploy-slack-bot.yml`: `slack-bot/` 配下の変更で trigger、Cloud Run へデプロイ
- `update-races.yml`: 土曜 5:00 JST cron で当日出走表を取得し自動 PR
- Bedrock SigV4 + floating tag 問題は SINIS で踏んだので、tag は SHA pin する

### Remote Control の運用
- 自宅 PC で `tmux` 内に Claude Code を起動しっぱなしにする
- `/config` で「Enable Remote Control for all sessions」を true にしておく
- スマホ通知のため Claude Code v2.1.110 以降を使用

---

## 9. セキュリティ・プライバシー

- `data/race.db`・`data/cache/` は gitignore（追跡対象・取得データを公開リポジトリに残さない）。**watchlist は廃止**し、分析対象は都度プロンプトで指定する
- Slack bot の API キー・Anthropic API キーは Secret Manager / GitHub Secrets で管理
- keibalab スクレイピングは個人利用範囲・低レート・データ再配布はしない（独自指標 α/β/Ω指数 は保存しない）

---

## 10. 注意事項（kabu と同じ思想）

- **賭博助言ではない**：最終判断はユーザー自身の責任
- データ遅延・欠損あり、直前情報は手動確認推奨
- プレイブック陳腐化に注意、定期レビュー必須
- 期待値の高い買い目を提示するが、的中保証ではない

---

## 11. 開発の進め方（提案）

### Phase 1: A の MVP（kabu 模写）
1. kabu の `.claude/` 構成をコピーして競馬ドメインに翻訳
2. `pedigree-analyst` と `devils-advocate` だけで `/analyze` を動かす
3. `scripts/fetch_races.py` で 1 レース分取得できるようにする（実装は keibalab.jp）
4. SQLite スキーマと `db.py` を整備

### Phase 2: A の拡充
5. 残り 3 エージェント（track / race-context / macro-scout）を追加
6. プレイブック 3〜4 本（東京 2400、中山 2500、ワイド戦略、GI 傾向）
7. `/debate`、`/recommend` を実装
8. Remote Control での運用検証

### Phase 3: B の MVP
9. `slack-bot/` のスケルトン作成（Slack Bolt + Socket Mode）
10. `.claude/agents/*.md` をプロンプトとして読み込む共通ロジック
11. orchestrator.py で 5 エージェントの API ループ実装
12. Cloud Run へデプロイ、Slack `/keiba` コマンド動作確認

### Phase 4: B の運用化
13. 土曜朝 cron バッチ
14. ワイド予算最適化ロジックを A・B 共通モジュール化
15. プッシュ通知連携

---

## 12. 未決事項・要相談

- [x] スクレイピング vs JRA-VAN → **keibalab.jp スクレイピングをメインに採用**（無料・/db/ robots 許可・日付ベース race_id。JRA-VAN CSV は併用パスとしてスタブのみ）
- [ ] Slack bot のチャンネル設計（DM 専用？ 公開チャンネル併用？）
- [ ] `/recommend` の評価関数（期待値ベース or 確信度ベース or 複合）
- [ ] 過去レース結果の蓄積範囲（直近 3 年？ 5 年？）
- [ ] エージェント間の意見対立時の合議ルール（多数決？ devils-advocate の veto？）

これらは Phase 1 を進めながら順次決めていく。

---

## 参考

- kabu リポジトリ: https://github.com/d-hiroshima/kabu
- Claude Code ドキュメント: https://docs.claude.com/en/docs/claude-code/overview
- Remote Control: https://code.claude.com/docs/en/remote-control
- Agent Teams: https://code.claude.com/docs/en/agent-teams
