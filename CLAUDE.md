# 競馬予想分析プロジェクト

中央競馬（JRA）の重賞・条件戦を対象とする個人予想支援。複数視点と反証思考を強制する設計。`d-hiroshima/kabu` の構成を競馬ドメインに翻訳した姉妹プロジェクト。

## 対象
- **中央競馬（JRA）**: GI / GII / GIII 重賞を主、条件戦は注目レースのみ
- **モバイル併用**: 出先からは Claude Code Remote Control 経由で `/recommend` 等を投げる

## 二系統運用（A + B）

このリポジトリは 2 つの運用形態を同居させる：

| 形態 | 用途 | 場所 |
| --- | --- | --- |
| **A. Claude Code + Remote Control** | 出先のレース前確認、`/debate` の多視点議論 | `.claude/`（このフォルダ） |
| **B. Slack bot（Cloud Run 常駐）** | 土曜朝の重賞バッチ、PC オフでも動く | `slack-bot/` |

両方が **`.claude/agents/*.md` の system prompt を共有** する（Slack bot は `slack-bot/prompts/load_agent_prompt.py` で読み込み再利用）。プロンプトの一元管理が設計のキモ。

詳細は `docs/design.md` を参照。

## ディレクトリ構成
```
.claude/agents/      # サブエージェント定義（5体）
.claude/skills/      # 分析手順スキル
.claude/commands/    # /analyze などスラッシュコマンド
docs/design.md       # ハンドオフ設計ドキュメント
docs/playbooks/      # コース別・グレード別の重量プレイブック
scripts/             # データ取得・DB 操作
data/race.db         # SQLite（出走表・結果・血統）
slack-bot/           # B 形態の本体（Slack Bolt + Anthropic API）
```

## エージェント編成
| Agent | 役割 |
|---|---|
| `pedigree-analyst` | 血統・産駒傾向・配合適性 |
| `track-analyst` | コース適性・距離・脚質・馬場状態・**騎手/厩舎実績** |
| `race-context-analyst` | レースグレード・出走馬レベル・ペース予想・展開 |
| `devils-advocate` | **反対役・本命崩しの穴党・毎回必須** |
| `macro-scout` | 天候・馬場・調教師コメント・直前情報（WebFetch、`/recommend` で起動） |

## 3つの動作モード

**通常モード（`/analyze <race-id>`）— Subagents**
メインClaudeが司会・統合。デフォルトは `pedigree-analyst` + `devils-advocate` の2体。コース論点が中心なら `track-analyst` 追加、レース層が論点なら `race-context-analyst` 追加。`--full` で全員招集。`devils-advocate` は他全員の結論を踏まえて最後に呼ぶ。

**議論モード（`/debate <race-id>`）— Agent Teams**（実験的機能、`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` 有効化済み）
メインClaudeがチームリーダーとして4メンバーを生成。メンバー同士が SendMessage で直接議論・反論し合い、最低1ラウンドの議論を経て結論を出す。重要レース専用（コストは `/analyze` の3-5倍）。

**推奨モード（`/recommend`）— Agent Teams**
5メンバー（macro-scout / race-context / pedigree / track / critic）でフェーズ別に進行。直前情報・天候 → レース選別 → 血統・コース並列評価 → 評論家の反証ラウンド → Top 3-5 確定。当日／週末の「買うべきレース」と買い目を提案。

各エージェント定義の末尾に「Team mode（`/debate`）」「Recommend mode（`/recommend`）」セクションがあり、モード別の挙動が定義されている。

## 出力フォーマット規約（全エージェント必須）

統合・各エージェントの **必須セクション・必須カラム・型** は **`docs/output-schema.md`** を正とする。スキーマ違反は統合時にエラー扱い（メインClaude が再依頼）。

最低限の共通ルール:
```
- 強気度: -5（強い消し） 〜 +5（強い本命）
- 確信度: 1 〜 5
- 根拠: 3点
- 反証条件: "What would change my mind?" 1点
```

## レース・馬の表記
- レース: **keibalab 形式の日付ベース `race_id`**（12桁 = `YYYYMMDD`＋場コード2桁＋R2桁。例: `202605030811` = 2026-05-03 京都11R）。keibalab の DB URL（`/db/race/<race_id>/`）と一致する。**netkeiba 形式（年+場+回+日+R）とは別物**（相互変換にはカレンダー照合が要るため非対応）。場コードは 01-10（地方/海外は範囲外）
- 馬: `horse_id`（10桁、netkeiba/keibalab 共通）
- コース: `<競馬場>-<距離>`（例: `tokyo-2400`、`nakayama-2500`）。プレイブック名と一致

## データ取り扱い方針（重要）

**「変わらないものはローカル DB／変わるものは都度取得」** が設計の柱。

### 不変データ → `data/race.db` に永続化
取得済みなら DB を見るだけで済む。`scripts/fetch_*.py` で取得しキャッシュ。
- **races**（レースのコース・距離・グレード・確定後の馬場・天候）
- **entries**（出馬投票締切後の馬番・枠・斤量・騎手・厩舎）
- **results**（着順・タイム・上がり3F・通過順）
- **horses**（生年・血統・父・母父）
- **pedigree_stats**（種牡馬の産駒成績集計。keibalab はコース×距離×馬場のクロス表を提供しないため、**ローカルの results×horses×races を SQL 集計して再構築**する＝産駒の戦績が貯まるほど精度が上がる）

### 揮発データ → 都度 WebFetch（DB に入れない）
鮮度が命の情報なので、必要時に `macro-scout` がその場で取得し、その分析だけに使う。キャッシュしない。
- **オッズ・人気**（発走 1 分前まで動く）
- **馬体重・前走比**（パドック直前にしか確定しない）
- **馬場発表・天候**（当日朝〜直前で変わる）
- **調教気配・調教師コメント**
- **直前の乗り替わり・出走取消・除外**

理由:
1. オッズや馬場を DB に書くと「いつのオッズか」問題が出て参照側が必ず鮮度判定する羽目になる
2. macro-scout が責任を持って都度取得するほうが、エージェント間の責務分担が明確
3. keibalab スクレイピングの叩く回数を最小化できる（規約・rate limit 配慮）

## セットアップ（ローカル実行環境）

- この環境のインタープリタは **`python3`**（`python` コマンドは無い）。ドキュメント中のコマンドはすべて `python3` で実行する
- 依存導入（初回のみ）: `pip3 install --user --break-system-packages -r requirements.txt`（requests / beautifulsoup4 / lxml。venv 派は `python3 -m venv .venv` でも可）
- `sqlite3` CLI は環境に無い。DB 参照は `python3 scripts/db.py card/history/...`（後述）か `python3 -c "import sqlite3; ..."` を使う
- DB スキーマと検証済み SQL 例の正は **`docs/db-schema.md`**（`python3 scripts/db.py schema-doc` で自動生成）

## データ取得
取得元は **keibalab.jp**（`scripts/keibalab.py` が HTTP＋HTMLキャッシュ＋パースを集約）。ブラウザ相当 UA・連続取得は最低 2 秒スリープ・取得済み HTML は `data/cache/` に保存して再取得を避ける。
- `python3 scripts/fetch_races.py <race-id>...` で出走表を取得 → `races`/`entries` 保存。**発走前は馬柱（umabashira）、確定後は結果ページ**を自動で使い分ける
- `python3 scripts/fetch_results.py <id>...` で結果/戦績を取得。**10桁=馬の全戦績（`results`+過去`races`）/ 12桁=1レース全着順＋払戻**を自動判別
- `python3 scripts/fetch_pedigree.py <horse-id>...` で血統 → `horses` 保存
- `python3 scripts/fetch_pedigree.py --sire-stats <sire-id>` で産駒成績を **ローカル集計** → `pedigree_stats`（先に産駒の戦績取得が必要）
- 取得済みなら自動スキップ（**実データ行の有無＋当日 fetch_log で判定**。空ログだけでは取得済み扱いにしない）。`--force` で強制再取得
- 取得対象は **都度引数で指定**（race_id / horse_id を複数可、または `--race <race_id>`）。固定の一括リスト（watchlist）は持たない
- **オッズ・馬体重・馬場発表は取得対象外**。macro-scout が都度 WebFetch する
- keibalab 独自指標 **α/β/Ω指数 は保存・再配布しない**（同社 IP）

データソース：**keibalab.jp スクレイピング**（無料・`/db/` は robots 許可。規約・rate limit に配慮し低レート・個人利用・非再配布）を主とし、規約クリーンな一括取得が必要なら JRA-VAN Data Lab CSV（`scripts/import_jravan_csv.py`）を併用。詳細は memory の data-source-decision を参照。

## 分析対象の指定（プロンプトで都度指定）

固定のウォッチリスト（watchlist.json）は**廃止**。プライバシー（公開リポジトリに追跡対象を残さない）と運用簡素化のため、**分析したいレース／馬はその都度プロンプト（引数）で渡す**。keibalab の URL を貼ってもよい（ID を抽出して使う）。

### 1. レース分析
- `/analyze <race_id>` または `/recommend <race_id>...` でレースを指定
- 論点: 買い目、軸馬選定、点数配分
- race_id は keibalab 日付ベース 12桁（`YYYYMMDD+場コード+R`）。レースURL（`/db/race/<race_id>/...`）も可

### 2. 馬分析
- `/analyze --horse <horse_id>` で馬を指定
- 論点: 次走の出走予定確認、適性レース判定、買い時
- horse_id は 10桁。馬URL（`/db/horse/<horse_id>/`）も可

対象が DB に無ければ、`fetch_*.py`（不変データ）/ macro-scout の WebFetch（揮発データ）で取得してから分析する。

## ワイド戦略（買い目最適化）

`/recommend --budget=3000 --type=wide --points=6` のような形で予算最適化を呼べる。
- `--budget`: 総予算（円）
- `--type`: `win` / `place` / `wide` / `umaren` / `umatan` / `sanrenpuku` / `sanrentan`
- `--points`: 点数上限
- `--ev-threshold`: 期待値しきい値（例: 1.2 で期待値 1.2 倍以上のみ）

ロジックは `docs/playbooks/wide-strategy.md` 参照。**A・B で共通モジュール化**するのが Phase 4 の目標。

## 直前情報の取り扱い
- 揮発データ（馬場・天候・馬体重・オッズ・調教師コメント）は **キャッシュせず都度取得**（macro-scout が WebFetch）
- 上記「データ取り扱い方針」に従い、揮発データは DB には入れない
- レース当日 30 分前以降の情報は手動で再確認推奨

## 重要な注意
- 出力は **賭博助言ではない**。最終判断はユーザー自身の責任。
- データソース（keibalab 等）には遅延・欠損あり。直前情報は要確認。
- コース別プレイブックは陳腐化する。四半期ごとにレビュー。
- 期待値ベースで提案するが、**的中保証ではない**。
