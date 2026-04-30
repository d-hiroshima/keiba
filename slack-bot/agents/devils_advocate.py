"""devils-advocate の Slack bot 実装（Phase 3 で実装）。

A 形態と同じく「最後に必ず通す」設計。orchestrator.py から最後に呼ばれる前提。
"""

from __future__ import annotations

from typing import Any

from prompts import load_agent

AGENT_NAME = "devils-advocate"


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    """他エージェントの結論を受け取り、反証ラウンドを実施する。

    input_data:
        race_id: str
        prior_results: list[dict]   # pedigree / track / race_context の出力
        ...

    return:
        {
            "agent": "devils-advocate",
            "weak_points": [...],
            "miss_scenarios": [...],
            "anti_picks": [...],     # 穴馬候補
            ...
        }
    """
    agent_meta = load_agent(AGENT_NAME)
    raise NotImplementedError(
        f"{AGENT_NAME} の Slack bot 実装は Phase 3。"
        f" system_prompt は {len(agent_meta['system_prompt'])} 文字読み込み済み。"
    )
