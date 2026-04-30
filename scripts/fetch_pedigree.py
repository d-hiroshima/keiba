"""血統情報と種牡馬産駒成績を取得して SQLite に保存。

データソース第一候補は netkeiba。Phase 1 では実装スタブ。

使用例:
  python scripts/fetch_pedigree.py 2020100789
  python scripts/fetch_pedigree.py --race 202604030611  # レースの全出走馬の血統取得
  python scripts/fetch_pedigree.py --watchlist          # watchlist の horses + race 出走馬
  python scripts/fetch_pedigree.py --sire-stats <sire_id>  # 種牡馬の産駒成績集計
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect, init_db  # noqa: E402

WATCHLIST_PATH = Path(__file__).resolve().parent.parent / "watchlist.json"


def already_fetched_today(target_id: str, kind: str) -> bool:
    today = date.today().isoformat()
    with connect() as conn:
        row = conn.execute(
            "SELECT fetched_at FROM fetch_log WHERE target_id=? AND kind=?",
            (target_id, kind),
        ).fetchone()
    return bool(row and row["fetched_at"].startswith(today))


def fetch_horse_pedigree(horse_id: str, force: bool) -> int:
    """馬の血統情報を取得し horses テーブルに保存。

    TODO: Phase 1 で実装。
    取得 URL: https://db.netkeiba.com/horse/<horse_id>
    取得項目: 父・父父・母・母父・生年・性別・毛色・生産者
    """
    if not force and already_fetched_today(horse_id, "pedigree"):
        print(f"  [skip] horse {horse_id} (今日既に取得済み)")
        return 0
    print(f"  [todo] horse {horse_id}: 血統取得は Phase 1 で実装")

    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO fetch_log (target_id, kind, fetched_at) VALUES (?, 'pedigree', ?)",
            (horse_id, datetime.now().isoformat(timespec="seconds")),
        )
    return 0


def fetch_sire_stats(sire_id: str, force: bool) -> int:
    """種牡馬の産駒成績を全コース・全距離で集計取得。

    TODO: Phase 1 で実装。
    取得 URL: https://db.netkeiba.com/?pid=horse_detail&id=<sire_id>
    集計対象: 中央競馬、過去 3-5 年（陳腐化防止）
    出力テーブル: pedigree_stats
    """
    if not force and already_fetched_today(sire_id, "pedigree_stats"):
        print(f"  [skip] sire {sire_id} (今日既に取得済み)")
        return 0
    print(f"  [todo] sire {sire_id}: 産駒成績集計は Phase 1 で実装")

    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO fetch_log (target_id, kind, fetched_at) VALUES (?, 'pedigree_stats', ?)",
            (sire_id, datetime.now().isoformat(timespec="seconds")),
        )
    return 0


def horses_in_race(race_id: str) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT horse_id FROM entries WHERE race_id=?", (race_id,)
        ).fetchall()
    return [r["horse_id"] for r in rows]


def load_watchlist_targets() -> list[str]:
    with WATCHLIST_PATH.open(encoding="utf-8") as f:
        wl = json.load(f)
    horses: list[str] = list(wl.get("horses", []))
    for race_id in wl.get("races", []):
        horses.extend(horses_in_race(race_id))
    return list(dict.fromkeys(horses))  # 重複除去（順序維持）


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("horse_ids", nargs="*", help="horse_id")
    ap.add_argument("--race", metavar="RACE_ID", help="指定レースの全出走馬の血統取得")
    ap.add_argument("--watchlist", action="store_true", help="watchlist の horses + races の出走馬")
    ap.add_argument("--sire-stats", metavar="SIRE_ID", help="種牡馬の産駒成績集計を取得")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    init_db()

    if args.sire_stats:
        fetch_sire_stats(args.sire_stats, args.force)
        return

    targets: list[str] = list(args.horse_ids)
    if args.race:
        targets.extend(horses_in_race(args.race))
    if args.watchlist:
        targets.extend(load_watchlist_targets())

    targets = list(dict.fromkeys(targets))
    if not targets:
        ap.error("horse_id / --race / --watchlist / --sire-stats のいずれかが必要")

    for h in targets:
        try:
            fetch_horse_pedigree(h, args.force)
        except Exception as e:  # noqa: BLE001
            print(f"  [err]  {h}: {e}")
    print(f"完了: {len(targets)} 頭")


if __name__ == "__main__":
    main()
