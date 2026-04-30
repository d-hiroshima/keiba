"""Slack Bolt エントリポイント（Phase 3 で実装）。

Socket Mode で Slack に接続し、スラッシュコマンドや mention に応答する。
土曜朝バッチは `.github/workflows/update-races.yml` から HTTP もしくは
別エントリ（cli.py 等）として呼び出す想定。
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# このファイルが import されるとき、orchestrator.py の Phase 3 未実装が即座に落ちないよう
# 関数内で遅延 import する
load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
)


@app.command("/keiba")
def cmd_keiba(ack, command, respond):
    """`/keiba <race-id>` で個別レース予想。"""
    ack()
    args = (command.get("text") or "").strip().split()
    if not args:
        respond("使い方: `/keiba <race_id>` 例: `/keiba 202604030611`")
        return

    race_id = args[0]
    full = "--full" in args

    # Phase 3 で実装: orchestrator.analyze_race を呼んで結果を整形して返す
    respond(f"_(Phase 3 未実装)_ /keiba {race_id} を受け付けました。full={full}")


@app.command("/keiba-recommend")
def cmd_recommend(ack, command, respond):
    """`/keiba-recommend [--budget=3000 --type=wide --top=3]` で推奨レース。"""
    ack()
    text = (command.get("text") or "").strip()
    respond(f"_(Phase 3 未実装)_ /keiba-recommend {text} を受け付けました")


@app.event("app_mention")
def on_mention(event, say):
    say("こんにちは！ `/keiba <race-id>` または `/keiba-recommend` をお試しください。")


def main():
    app_token = os.environ.get("SLACK_APP_TOKEN")
    if not app_token:
        log.error("SLACK_APP_TOKEN is not set; copy .env.example to .env and fill in tokens")
        sys.exit(1)
    handler = SocketModeHandler(app, app_token)
    log.info("Starting Slack bot (Socket Mode)")
    handler.start()


if __name__ == "__main__":
    main()
