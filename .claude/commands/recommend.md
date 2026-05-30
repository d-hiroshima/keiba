---
description: Agent Teams を組んで「今日／週末買うべきレース」をTop3-5提案。直前情報・コース・血統を踏まえる。/recommend / /recommend --budget=3000 --type=wide --points=6 / /recommend --top=3
---

引数: $ARGUMENTS

> **前提**:
> - `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` 有効化済み（`.claude/settings.json`）
> - Claude Code v2.1.32+
> - レース DB が古い場合、事前に `python scripts/fetch_races.py <race_id>...`（対象レースを明示）の実行を提案
>
> **コスト警告**: `/analyze` の数倍のトークンを使用。直前情報の WebFetch が多発。土曜朝・日曜朝の利用想定。

# 手順

## ステップ1: 事前準備
1. 引数解析: `--budget=<円>` / `--type=<券種>` / `--points=<点数>` / `--ev-threshold=<期待値>` / `--top=<N>`
2. 母集団確定: 当日開催の重賞 ＋ **プロンプトで指定されたレース**（race_id / keibalab URL。無ければ当日重賞のみ）
3. データ鮮度: `races` テーブルの最新日付を確認、古ければ取得を推奨

## ステップ2: チーム生成

`recommend-races` スキルに従い、Agent Teams を作成:

> 「直前情報を踏まえて買うべきレース・買い目を Top 3-5 で提案する分析チームを作成してください。次の subagent 定義を使って5メンバーを生成：
>
> - `macro-scout` 名: `scout`
> - `race-context-analyst` 名: `context`
> - `pedigree-analyst` 名: `pedigree`
> - `track-analyst` 名: `track`
> - `devils-advocate` 名: `critic`
>
> 母集団は当日開催の重賞 + プロンプトで指定されたレース。フェーズ1: scout と context を並列実行。フェーズ2: 候補5-8レースを抽出。フェーズ3: pedigree と track で各レースの上位人気＋穴候補を深掘り評価。フェーズ4: critic が反論質問を送って議論し、各レースに穴馬を提示。フェーズ5: 最終Top3-5確定 + 買い目案。」

## ステップ3: 進行モニタリング
- フェーズ1終了を確認してからフェーズ2へ
- フェーズ3で候補レース数が8を超えたら絞り込み指示
- フェーズ4の議論が同じ論点で堂々巡りなら2ラウンドで打ち切り
- 最終出力は `recommend-races.md` の出力フォーマットに従う

## ステップ4: 予算配分（オプション）

`--budget` 指定時は `docs/playbooks/wide-strategy.md` のロジックに従い、Top レースの本命確信度 × 想定オッズ × 期待値で予算配分。期待値しきい値（既定 1.0）未満は除外。

## ステップ5: クリーンアップ
分析完了後、必ず「Clean up the team」をリーダーから指示。

# よくあるオプション

```
/recommend                                 # 当日全重賞、Top 5
/recommend 202605030811 202602210511        # 当日重賞 + 指定レースを母集団に追加
/recommend --top=3                         # Top 3 のみ提示
/recommend --budget=3000 --type=wide       # ワイド3000円配分
/recommend --budget=10000 --type=sanrenpuku --points=12  # 三連複 12点
/recommend --ev-threshold=1.2              # 期待値 1.2 倍以上のみ
/recommend --conservative                  # 保守的（本命級・想定オッズ 5倍以下）
```

# 注意

- このコマンドは **賭博助言ではない**。最終判断はユーザーの責任
- 直前情報は流動的なので、**実行時刻** を出力に明示
- 推奨レースは **想定オッズと期待値の根拠** 付きで提示
- 出力後、**3 時間以上経過した推奨は鮮度切れ**（直前で馬場が変わる可能性）として扱う
