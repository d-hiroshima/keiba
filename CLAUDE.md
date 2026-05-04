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
watchlist.json       # 注目レース・注目馬・注目コース
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
```
- 強気度: -5（強い消し） 〜 +5（強い本命）
- 確信度: 1 〜 5
- 根拠: 3点
- 反証条件: "What would change my mind?" 1点
```

## レース・馬の表記
- レース: netkeiba 形式の `race_id`（12桁、例: `202604030611` = 2026年4回東京6日11R）
- 馬: netkeiba 形式の `horse_id`（10桁）
- コース: `<競馬場>-<距離>`（例: `tokyo-2400`、`nakayama-2500`）。プレイブック名と一致

## データ取り扱い方針（重要）

**「変わらないものはローカル DB／変わるものは都度取得」** が設計の柱。

### 不変データ → `data/race.db` に永続化
取得済みなら DB を見るだけで済む。`scripts/fetch_*.py` で取得しキャッシュ。
- **races**（レースのコース・距離・グレード・確定後の馬場・天候）
- **entries**（出馬投票締切後の馬番・枠・斤量・騎手・厩舎）
- **results**（着順・タイム・上がり3F・通過順）
- **horses**（生年・血統・父・母父）
- **pedigree_stats**（種牡馬の産駒成績集計）

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
3. netkeiba スクレイピングの叩く回数を最小化できる（規約・rate limit 配慮）

## データ取得
- `python scripts/fetch_races.py <race-id>...` で出走表（不変部分）を取得 → SQLite 保存
- `python scripts/fetch_results.py <race-id>...` で確定結果を取得
- `python scripts/fetch_pedigree.py <horse-id>...` で血統情報を取得
- 同日内に取得済みならスキップ（`--force` で強制）
- ウォッチリスト一括更新は `python scripts/fetch_races.py --watchlist`
- **オッズ・馬体重・馬場発表は `fetch_races.py` の対象外**。macro-scout が都度 WebFetch する

データソース：netkeiba スクレイピング（規約・rate limit に注意）または JRA-VAN Data Lab CSV（`scripts/import_jravan_csv.py`）。

## 関心対象の二系統

ユーザーが「関心を持つ対象」は **2系統** から判定する。

### 1. 注目レース（`watchlist.json` の `races`）
- 出馬確定後の重賞、条件戦で気になるレース
- 分析時の論点: 買い目、軸馬選定、点数配分

### 2. 注目馬（`watchlist.json` の `horses`）
- 過去レースから追跡している馬
- 分析時の論点: 次走の出走予定確認、適性レース判定、買い時

### 取り扱いルール
- レースが **注目レース** → `/analyze <race-id>` で多視点予想
- 馬が **注目馬** → `/analyze --horse <horse-id>` で適性・次走分析
- ウォッチに無いレース → 一般分析後に「ウォッチに追加するか」を提示

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
- データソース（netkeiba 等）には遅延・欠損あり。直前情報は要確認。
- コース別プレイブックは陳腐化する。四半期ごとにレビュー。
- 期待値ベースで提案するが、**的中保証ではない**。
