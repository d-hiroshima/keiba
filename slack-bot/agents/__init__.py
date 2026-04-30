"""Slack bot 内の各エージェント実装。

`.claude/agents/*.md` の system prompt を `prompts/load_agent_prompt.py` で読み込み、
Anthropic API でメッセージを送るシンプルなラッパー群。

各モジュールは `run(input_data: dict) -> dict` インターフェースを持ち、
orchestrator.py から呼ばれる。
"""
