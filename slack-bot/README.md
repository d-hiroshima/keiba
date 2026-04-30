# keiba slack-bot（B 形態）

Slack 経由で keiba エージェントチームを呼び出す常駐 bot。Cloud Run / Fargate / Render に常駐させ、Socket Mode で Slack に常時接続する。

> **設計のキモ**: `.claude/agents/*.md` の system prompt を `prompts/load_agent_prompt.py` で読み込んで再利用する。プロンプトの一元管理。

## 動作概要

- **インタラクティブ**: Slack DM / チャンネルで `/keiba <race-id>` `/keiba-recommend` 等のスラッシュコマンド
- **バッチ**: 土曜朝 5:00 JST cron（GitHub Actions の `update-races.yml`）→ 当日重賞の予想を Slack 投稿

## 構成

```
slack-bot/
├── app.py                          # Slack Bolt エントリポイント
├── orchestrator.py                 # 自前 multi-agent オーケストレーション
├── agents/
│   ├── __init__.py
│   ├── pedigree.py
│   ├── track.py
│   ├── race_context.py
│   ├── devils_advocate.py
│   └── macro_scout.py
├── prompts/
│   └── load_agent_prompt.py        # .claude/agents/*.md を読み込み
├── deploy/
│   ├── Dockerfile
│   └── docker-compose.yml
├── requirements.txt
└── .env.example
```

## ローカル起動

```bash
cd slack-bot
cp .env.example .env
# .env に以下を設定:
#   ANTHROPIC_API_KEY=sk-ant-...
#   SLACK_BOT_TOKEN=xoxb-...
#   SLACK_APP_TOKEN=xapp-...
#   SLACK_SIGNING_SECRET=...
pip install -r requirements.txt
python app.py
```

## デプロイ（Cloud Run 想定）

```bash
gcloud run deploy keiba-slack-bot \
  --source . \
  --region asia-northeast1 \
  --no-allow-unauthenticated \
  --set-secrets ANTHROPIC_API_KEY=anthropic-api-key:latest,SLACK_BOT_TOKEN=slack-bot-token:latest,...
```

CI/CD は `.github/workflows/deploy-slack-bot.yml` 参照。

## オーケストレーション

Claude Code の Agent Teams は API でそのまま使えないため、自前で順序制御：

1. `lead`（ユーザー入力をパース、データ準備）
2. `pedigree`, `track`, `race_context` を **並列**で API 呼び出し
3. 結果を `devils_advocate` に渡して **最後に**呼び出す
4. 統合判断を Slack に返す

詳細は `orchestrator.py` のコメント参照（Phase 3 で実装）。

## 状態

このディレクトリは **Phase 3 のスケルトン**。Phase 1-2 で `.claude/` の動作を固めた後、Phase 3 で実装に取りかかる。
