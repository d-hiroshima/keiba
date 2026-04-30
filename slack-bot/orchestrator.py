"""自前 multi-agent オーケストレーション（Phase 3 で実装）。

Claude Code の Agent Teams は API でそのまま使えないため、
ここで `lead → 並列分析 → critic（最後）` の順序を制御する。

設計方針:
- A 形態の `.claude/skills/analyze-race.md` と同じステップに従う
- pedigree / track / race_context は asyncio.gather で並列実行
- devils_advocate は **必ず最後** に呼ぶ（kabu の思想を継承）
"""

from __future__ import annotations

import asyncio
from typing import Any

from agents import devils_advocate, macro_scout, pedigree, race_context, track


async def analyze_race(race_id: str, *, full: bool = False) -> dict[str, Any]:
    """A 形態の `/analyze` を Slack bot から呼ぶ版。

    Args:
        race_id: netkeiba 形式の race_id
        full: True なら 5 エージェント全員、False ならデフォルト構成

    Returns:
        統合判断 dict
    """
    input_data = await _prepare(race_id)

    primary_agents = [pedigree, track, race_context]
    if full:
        primary_agents.append(macro_scout)

    primary_results = await asyncio.gather(
        *[asyncio.to_thread(a.run, input_data) for a in primary_agents],
        return_exceptions=True,
    )

    critic_input = {**input_data, "prior_results": primary_results}
    critic_result = await asyncio.to_thread(devils_advocate.run, critic_input)

    return _integrate(input_data, primary_results, critic_result)


async def _prepare(race_id: str) -> dict[str, Any]:
    """データ鮮度チェック + races / entries 読み込み（Phase 3 で実装）。"""
    raise NotImplementedError("Phase 3 で実装: scripts.db 経由で races/entries を読む")


def _integrate(
    input_data: dict[str, Any],
    primary_results: list[Any],
    critic_result: dict[str, Any],
) -> dict[str, Any]:
    """`.claude/skills/analyze-race.md` の出力フォーマットに合わせて統合（Phase 3 で実装）。"""
    raise NotImplementedError("Phase 3 で実装: 統合 markdown を組み立てる")


async def recommend_races(
    *,
    budget: int | None = None,
    bet_type: str | None = None,
    points: int | None = None,
    ev_threshold: float = 1.2,
    top_n: int = 5,
) -> dict[str, Any]:
    """A 形態の `/recommend` を Slack bot から呼ぶ版。

    フェーズ:
        1. macro_scout + race_context を並列で初期リサーチ
        2. 候補レース 5-8 に絞る
        3. pedigree + track で深掘り
        4. devils_advocate で反証ラウンド（穴馬提示）
        5. 統合 → 買い目最適化（budget 指定時は wide_strategy）
    """
    raise NotImplementedError("Phase 3 で実装: フェーズ別オーケストレーション")
