---
description: 議論型・多視点レース予想。Agent Teams を生成し、メンバー間で直接議論させて結論を出す。例 /debate 202604030611
---

引数: $ARGUMENTS

> **前提**: `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` が `.claude/settings.json` で有効化済み。Claude Code v2.1.32+。
>
> **コスト警告**: 通常の `/analyze` の **3-5倍のトークン**を使用します。各チームメンバーが独立した Claude Code インスタンスを動かすためです。日常の予想には `/analyze` を、GI レースや買い目で迷う重要レースにのみ `/debate` を使ってください。

`debate-race` スキルに従って、引数で渡された race_id を議論型で予想してください。

# 手順（リーダー = メインClaude が実施）

## ステップ1: 事前準備

1. race_id を抽出・正規化（netkeiba 形式 12桁）
2. `data/race.db` の `races` テーブルでコース・距離・グレード取得
3. データ鮮度を確認:
   ```
   python scripts/fetch_races.py <race_id>
   python scripts/fetch_pedigree.py --race <race_id>
   ```
4. プレイブック（`docs/playbooks/<course>-<distance>.md`）の存在確認

## ステップ2: チーム生成

以下の指示でエージェントチームを作成（自然言語でClaude Codeに依頼）：

> 「`<race_id>`（<course> <distance>m <grade>）について議論型のレース予想を行うエージェントチームを作成してください。次の subagent 定義を使って4チームメンバーを生成：
>
> - `pedigree-analyst` 名: `pedigree`
> - `track-analyst` 名: `track`
> - `race-context-analyst` 名: `context`
> - `devils-advocate` 名: `critic`
>
> 各メンバーは初期分析を提示した後、`critic` が他メンバーに SendMessage で反論質問を送ります。各メンバーは反論または部分修正で応答し、最低1ラウンド議論を行います。`context` は `docs/playbooks/<course>-<distance>.md` を必読です。」

## ステップ3: 議論進行のモニタリング

リーダーは以下を監督：
- 全メンバーが初期分析を提示したか
- `critic` が各メンバーに反論質問を送ったか
- 議論が **同じ論点を繰り返している** 場合 → 「次の論点に進んで」と介入
- 議論が **収束した** 場合 → 「最終結論をまとめて」と指示
- 議論が **メイン論点から外れた** 場合 → 「論点を <X> に戻して」と介入

## ステップ4: 統合判断

`debate-race.md` の「フェーズ4: 統合判断」フォーマットで出力。

## ステップ5: チームクリーンアップ（必須）

分析完了後、リーダーから「Clean up the team」と指示してチームを解散。

> **重要**: 解散しないとセッション切替後にゾンビ状態のチームメンバーが残る場合あり。

# モード使い分けの目安

| 状況 | 推奨コマンド |
|---|---|
| ウォッチ重賞の事前確認 | `/analyze --quick` |
| 個別レースの通常予想 | `/analyze` |
| **GI レースの本命検討** | **`/debate`** |
| **本命と対抗で意見が割れそうな複雑レース** | **`/debate`** |

# トラブルシューティング

| 症状 | 対処 |
|---|---|
| `/agents` でチームメンバーが見えない | Shift+Down でサイクル、または分割ペインモードに切替 |
| 議論が止まる | リーダーから「次の論点に進んで」と直接介入 |
| トークン消費が異常に多い | チームメンバー数を3に減らす、または `/analyze` に切替 |
| 議論終了後もチームが残る | `Clean up the team` を必ず実行 |
