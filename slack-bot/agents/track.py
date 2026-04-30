"""track-analyst の Slack bot 実装（Phase 3 で実装）。"""

from __future__ import annotations

from typing import Any

from prompts import load_agent

AGENT_NAME = "track-analyst"


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    agent_meta = load_agent(AGENT_NAME)
    raise NotImplementedError(
        f"{AGENT_NAME} の Slack bot 実装は Phase 3。"
        f" system_prompt は {len(agent_meta['system_prompt'])} 文字読み込み済み。"
    )
