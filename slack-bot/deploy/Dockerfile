FROM python:3.12-slim

WORKDIR /app

# 依存をキャッシュさせる
COPY slack-bot/requirements.txt /app/slack-bot/requirements.txt
RUN pip install --no-cache-dir -r /app/slack-bot/requirements.txt

# .claude/agents/ と docs/playbooks/ もイメージに含める（プロンプト一元管理のため）
COPY .claude/agents /app/.claude/agents
COPY docs/playbooks /app/docs/playbooks
COPY scripts /app/scripts
COPY slack-bot /app/slack-bot

ENV PYTHONUNBUFFERED=1
ENV KEIBA_AGENT_PROMPTS_DIR=/app/.claude/agents
ENV KEIBA_PLAYBOOKS_DIR=/app/docs/playbooks
ENV KEIBA_DB_PATH=/app/data/race.db

WORKDIR /app/slack-bot
CMD ["python", "app.py"]
