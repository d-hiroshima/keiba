"""自前 multi-agent オーケストレーション（Phase 3 で実装）。

Claude Code の Agent Teams は API でそのまま使えないため、
ここで `lead → 並列分析 → critic（最後）` の順序を制御する。

設計方針:
- A 形態の `.claude/skills/analyze-race.md` と同じステップに従う
- pedigree / track / race_context は asyncio.gather で並列実行
- devils_advocate は **必ず最後** に呼ぶ（kabu の思想を継承）
- 各エージェント結果は `scripts/validate_output.validate` でスキーマ検証する
  （`docs/output-schema.md` 準拠。違反は SCHEMA_VIOLATION ログ）
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from agents import devils_advocate, macro_scout, pedigree, race_context, track

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from validate_output import validate as validate_schema  # noqa: E402

AGENT_TYPE_MAP = {
    "pedigree": "pedigree",
    "track": "track",
    "race_context": "race-context",
    "macro_scout": "macro-scout",
    "devils_advocate": "devils",
}


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

    for agent, result in zip(primary_agents, primary_results):
        _validate_agent_output(agent.__name__, result)

    critic_input = {**input_data, "prior_results": primary_results}
    critic_result = await asyncio.to_thread(devils_advocate.run, critic_input)
    _validate_agent_output("devils_advocate", critic_result)

    return _integrate(input_data, primary_results, critic_result)


def _validate_agent_output(agent_module_name: str, result: Any) -> None:
    """各エージェントの Markdown 出力を `docs/output-schema.md` で検証。

    違反は SCHEMA_VIOLATION ログを残すが、現状は処理を止めない（Phase 3 で
    再依頼ロジックを足す予定）。
    """
    if isinstance(result, Exception):
        return  # gather 例外は別ハンドラで処理
    text = result if isinstance(result, str) else result.get("markdown", "")
    if not text:
        return

    short_name = agent_module_name.rsplit(".", 1)[-1]
    target_type = AGENT_TYPE_MAP.get(short_name)
    validation = validate_schema(text, target_type)
    if not validation.ok:
        for v in validation.violations:
            if v.severity == "error":
                print(f"SCHEMA_VIOLATION [{short_name}] {v.message}")


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
