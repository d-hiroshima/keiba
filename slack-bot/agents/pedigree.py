"""pedigree-analyst の Slack bot 実装（Phase 3 で実装）。

`.claude/agents/pedigree-analyst.md` の system prompt を再利用する。
"""

from __future__ import annotations

from typing import Any

from prompts import load_agent

AGENT_NAME = "pedigree-analyst"


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    """1 レース・1 馬群に対する血統分析を返す。

    input_data:
        race_id: str
        horses: list[dict]    # entries テーブルから取得した出走馬
        course: str
        distance: int
        surface: str

    return:
        {
            "agent": "pedigree-analyst",
            "results": [
                {"horse_id": ..., "stance": +X, "confidence": Y, "reasons": [...], ...},
                ...
            ],
            "raw": "<モデルの生出力>",
        }

    TODO Phase 3:
    1. load_agent(AGENT_NAME) で system_prompt を取得
    2. input_data から user_message を組み立てる（出走馬一覧、コース・距離など）
    3. Anthropic API（claude-opus-4-7）で呼び出し、prompt caching を有効化
    4. 出力フォーマット規約（強気度・確信度・根拠・反証条件）に沿ってパース
    """
    agent_meta = load_agent(AGENT_NAME)
    raise NotImplementedError(
        f"{AGENT_NAME} の Slack bot 実装は Phase 3。"
        f" system_prompt は {len(agent_meta['system_prompt'])} 文字読み込み済み。"
    )
