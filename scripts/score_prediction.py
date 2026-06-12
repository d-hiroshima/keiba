"""予想 Markdown（predictions/<race_id>-*.md）を結果・払戻と突合して採点する。

「予想 → 結果 → 採点 → 教訓」ループの採点段。/review-race コマンドから呼ばれる。

前提:
  - 予想 md は docs/output-schema.md §4 準拠（全頭評価サマリ表に「選定」列、買い目テーブル）
  - レース結果・払戻が DB に取得済み（python3 scripts/fetch_results.py <race_id>）
  - 出走表（馬番→馬の対応）が DB に取得済み（python3 scripts/fetch_races.py <race_id>）

使用例:
  python3 scripts/score_prediction.py predictions/202606070511-yasuda-kinen.md
  python3 scripts/score_prediction.py predictions/202606070511-yasuda-kinen.md --append
    （--append は md 末尾に「## 結果検証（自動採点）」セクションを追記する）

終了コード: 0=採点完了 / 1=採点不能（結果未取得・パース不能）
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect, init_db  # noqa: E402
from validate_output import _iter_tables  # noqa: E402

_BET_WORDS = {
    "単勝": "win", "複勝": "place", "枠連": "wakuren", "馬連": "umaren",
    "ワイド": "wide", "馬単": "umatan",
    "三連複": "sanrenpuku", "3連複": "sanrenpuku",
    "三連単": "sanrentan", "3連単": "sanrentan",
}
_ORDERED_TYPES = {"umatan", "sanrentan"}  # 着順固定の券種（並べ替えない）
_MARKS = ("◎", "○", "▲", "△", "▽")


@dataclass
class Bet:
    bet_type: str
    combination: str  # 正規化済み（順不同券種は昇順 '5-13-17'）
    amount: int       # 円


def _norm_combo(combo: str, bet_type: str) -> str:
    nums = combo.split("-")
    if bet_type not in _ORDERED_TYPES:
        nums = sorted(nums, key=int)
    return "-".join(nums)


def parse_race_id_from(path: Path, text: str) -> str | None:
    m = re.match(r"(\d{12})", path.name)
    if m:
        return m.group(1)
    m = re.search(r"^#\s*レース予想[:：]\s*(\d{12})", text, re.MULTILINE)
    return m.group(1) if m else None


def parse_marks(text: str) -> dict[int, str]:
    """全頭評価サマリ表から {馬番: 選定記号} を抽出。"""
    marks: dict[int, str] = {}
    for header, rows in _iter_tables(text):
        if "選定" not in header or "馬番" not in header:
            continue
        i_no, i_sel = header.index("馬番"), header.index("選定")
        for row in rows:
            if len(row) <= max(i_no, i_sel):
                continue
            m = re.fullmatch(r"\d+", row[i_no].strip("* "))
            sel = row[i_sel].strip("* ")
            if m and sel and sel[0] in _MARKS:
                marks[int(m.group())] = sel[0]
        if marks:
            break
    return marks


def parse_bets(text: str) -> list[Bet]:
    """買い目セクション（### <券種> ... の直下の表）から賭け目を抽出。"""
    bets: list[Bet] = []
    current_type: str | None = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#"):
            current_type = None
            for word, bt in _BET_WORDS.items():
                if word in line:
                    current_type = bt
                    break
        elif current_type and line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 3 and "合計" not in cells[0]:
                m = re.match(r"(\d+(?:-\d+)*)", cells[0])
                # 投資額カラム（3列目想定。「300 円」）
                ma = re.search(r"([\d,]+)\s*円", cells[2])
                if m and ma and "-" in m.group(1) or (m and current_type in ("win", "place") and ma):
                    if m and ma:
                        bets.append(Bet(
                            bet_type=current_type,
                            combination=_norm_combo(m.group(1), current_type),
                            amount=int(ma.group(1).replace(",", "")),
                        ))
        i += 1
    return bets


def score(race_id: str, marks: dict[int, str], bets: list[Bet]) -> dict | None:
    """DB の results / payouts と突合。結果未取得なら None。"""
    with connect() as conn:
        finish = {}  # post_position -> finish_position
        rows = conn.execute(
            """SELECT e.post_position no, r.finish_position fp, e.horse_name name,
                      r.popularity pop, r.win_odds
               FROM results r JOIN entries e
                 ON e.race_id = r.race_id AND e.horse_id = r.horse_id
               WHERE r.race_id=?""",
            (race_id,),
        ).fetchall()
        payout_rows = conn.execute(
            "SELECT bet_type, combination, payout_yen FROM payouts WHERE race_id=?",
            (race_id,),
        ).fetchall()
    if not rows:
        return None
    finish = {r["no"]: dict(r) for r in rows if r["no"] is not None}
    payouts = {
        (p["bet_type"], _norm_combo(p["combination"], p["bet_type"])): p["payout_yen"]
        for p in payout_rows
    }

    mark_results = []
    for no, mark in sorted(marks.items(), key=lambda kv: _MARKS.index(kv[1][0])):
        f = finish.get(no, {})
        mark_results.append({
            "no": no, "mark": mark, "name": f.get("name", "?"),
            "finish": f.get("fp"), "popularity": f.get("pop"),
            "win_odds": f.get("win_odds"),
        })

    bet_results = []
    invested = returned = 0
    for b in bets:
        pay = payouts.get((b.bet_type, b.combination))
        ret = (b.amount // 100) * pay if pay else 0
        invested += b.amount
        returned += ret
        bet_results.append({
            "bet_type": b.bet_type, "combination": b.combination,
            "amount": b.amount, "hit": pay is not None, "returned": ret,
        })

    return {
        "race_id": race_id,
        "marks": mark_results,
        "bets": bet_results,
        "invested": invested,
        "returned": returned,
        "roi": (returned / invested) if invested else None,
        "has_payouts": bool(payouts),
    }


_BET_JP = {v: k for k, v in _BET_WORDS.items() if k not in ("3連複", "3連単")}


def render(result: dict) -> str:
    lines = [
        "## 結果検証（自動採点）",
        "",
        f"採点対象: {result['race_id']} / scripts/score_prediction.py による機械突合",
        "",
        "### 印別着順",
        "| 印 | 馬番 | 馬名 | 着順 | 確定人気 | 確定単勝 |",
        "|---|---|---|---|---|---|",
    ]
    for m in result["marks"]:
        fin = m["finish"] if m["finish"] is not None else "着外/除外"
        lines.append(
            f"| {m['mark']} | {m['no']} | {m['name']} | {fin} | {m['popularity'] or '-'} |"
            f" {m['win_odds'] or '-'} |"
        )
    lines += [
        "",
        "### 買い目採点",
        "| 券種 | 買い目 | 投資 | 的中 | 払戻 |",
        "|---|---|---|---|---|",
    ]
    for b in result["bets"]:
        lines.append(
            f"| {_BET_JP.get(b['bet_type'], b['bet_type'])} | {b['combination']} |"
            f" {b['amount']}円 | {'○' if b['hit'] else '×'} | {b['returned']}円 |"
        )
    roi = f"{result['roi']:.0%}" if result["roi"] is not None else "-"
    lines += [
        "",
        f"**投資 {result['invested']}円 / 払戻 {result['returned']}円 / 回収率 {roi}**",
    ]
    if not result["has_payouts"]:
        lines.append("")
        lines.append("> ⚠️ payouts 未取得のため的中判定が不完全（fetch_results.py で再取得を）")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=Path, help="予想 Markdown（predictions/...md）")
    ap.add_argument("--race-id", help="race_id 明示（省略時はファイル名/ヘッダから）")
    ap.add_argument("--append", action="store_true", help="md 末尾に採点セクションを追記")
    args = ap.parse_args()

    init_db()
    text = args.file.read_text(encoding="utf-8")
    race_id = args.race_id or parse_race_id_from(args.file, text)
    if not race_id:
        print("[err] race_id をファイル名（12桁プレフィクス）かヘッダから特定できない")
        return 1

    marks = parse_marks(text)
    bets = parse_bets(text)
    if not marks:
        print("[err] 全頭評価サマリ表（選定列）がパースできない")
        return 1

    result = score(race_id, marks, bets)
    if result is None:
        print(f"[err] {race_id} の結果が DB に無い。先に実行:")
        print(f"  python3 scripts/fetch_races.py {race_id}")
        print(f"  python3 scripts/fetch_results.py {race_id}")
        return 1

    report = render(result)
    print(report)

    if args.append:
        if "## 結果検証（自動採点）" in text:
            print("\n[skip] 既に採点セクションがあるため追記しない（重複防止）")
        else:
            args.file.write_text(text.rstrip() + "\n\n" + report + "\n", encoding="utf-8")
            print(f"\n[ok] {args.file} に採点セクションを追記")
    return 0


if __name__ == "__main__":
    sys.exit(main())
