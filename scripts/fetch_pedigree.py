"""血統情報と種牡馬産駒成績を取得して SQLite に保存。

データ源: keibalab.jp（/db/horse/<id>/ の血統表）。

種牡馬産駒成績（pedigree_stats）について:
  keibalab はコース×距離×馬場のクロス集計表を HTML で提供していない（コメントアウト）。
  そのため --sire-stats は **ローカルの results×horses×races を SQL 集計** して再構築する。
  → 先に fetch_results.py で産駒の戦績を蓄積しておくほど精度が上がる（DB が活きる設計）。

使用例:
  python scripts/fetch_pedigree.py 2020103060
  python scripts/fetch_pedigree.py --race 202605030811   # レース出走馬の血統を一括取得
  python scripts/fetch_pedigree.py --sire-stats 11202426  # ローカルデータから産駒成績集計
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect, init_db  # noqa: E402
import keibalab  # noqa: E402


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _done_today(conn, horse_id: str) -> bool:
    """horses 行があり、かつ本日 fetch_log 済みなら True（空ログの罠を回避）。"""
    if not conn.execute("SELECT 1 FROM horses WHERE horse_id=?", (horse_id,)).fetchone():
        return False
    row = conn.execute(
        "SELECT fetched_at FROM fetch_log WHERE target_id=? AND kind='pedigree'",
        (horse_id,),
    ).fetchone()
    return bool(row and row["fetched_at"].startswith(date.today().isoformat()))


# --------------------------------------------------------------------------- #
# 馬の血統（/db/horse/<id>/）→ horses
# --------------------------------------------------------------------------- #
def fetch_horse_pedigree(horse_id: str, force: bool) -> int:
    with connect() as conn:
        if not force and _done_today(conn, horse_id):
            print(f"  [skip] horse {horse_id} (血統取得済み)")
            return 0
    try:
        data = keibalab.fetch_horse(horse_id, force=force)
    except Exception as e:  # noqa: BLE001
        print(f"  [err]  horse {horse_id}: 取得失敗 {e}")
        return 0

    ped, prof = data.get("pedigree", {}), data.get("profile", {})
    if not ped.get("sire"):
        print(f"  [warn] horse {horse_id}: 血統が取得できず（保存スキップ）")
        return 0

    now = _now()
    with connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO horses
            (horse_id, name, birthday, sex, color, sire, sire_id, dam, dam_id,
             broodmare_sire, broodmare_sire_id, grandsire, breeder, owner, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                horse_id, data.get("name"), prof.get("birthday"), prof.get("sex"),
                prof.get("color"), ped.get("sire"), ped.get("sire_id"),
                ped.get("dam"), ped.get("dam_id"), ped.get("broodmare_sire"),
                ped.get("broodmare_sire_id"), ped.get("grandsire"),
                prof.get("breeder"), prof.get("owner"), now,
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO fetch_log (target_id, kind, fetched_at) VALUES (?, 'pedigree', ?)",
            (horse_id, now),
        )
    print(
        f"  [ok]   horse {horse_id}: {data.get('name')} "
        f"（父{ped.get('sire')}／母父{ped.get('broodmare_sire')}）"
    )
    return 1


# --------------------------------------------------------------------------- #
# 種牡馬産駒成績（ローカル results×horses×races を集計）→ pedigree_stats
# --------------------------------------------------------------------------- #
def fetch_sire_stats(sire_id: str, force: bool) -> int:
    with connect() as conn:
        name_row = conn.execute(
            "SELECT sire FROM horses WHERE sire_id=? AND sire IS NOT NULL LIMIT 1",
            (sire_id,),
        ).fetchone()
        rows = conn.execute(
            """SELECT ra.course, ra.distance, ra.surface, re.finish_position AS fp
               FROM results re
               JOIN horses h ON h.horse_id = re.horse_id
               JOIN races  ra ON ra.race_id = re.race_id
               WHERE h.sire_id = ? AND ra.course != 'unknown'""",
            (sire_id,),
        ).fetchall()

    if not rows:
        print(
            f"  [warn] sire {sire_id}: 集計対象の産駒戦績がローカルに無い"
            f"（先に fetch_results.py で産駒の戦績を取得）"
        )
        return 0

    # (course, distance, surface) で集計（馬場別は集約 = track_condition NULL）
    agg: dict = {}
    for r in rows:
        key = (r["course"], r["distance"], r["surface"])
        a = agg.setdefault(key, [0, 0, 0, 0])  # starts, wins, 2nd, 3rd
        a[0] += 1
        if r["fp"] == 1:
            a[1] += 1
        elif r["fp"] == 2:
            a[2] += 1
        elif r["fp"] == 3:
            a[3] += 1

    sire_name = name_row["sire"] if name_row else None
    now = _now()
    with connect() as conn:
        conn.execute("DELETE FROM pedigree_stats WHERE sire_id=?", (sire_id,))
        for (course, distance, surface), (s, w, p, t) in agg.items():
            conn.execute(
                """INSERT INTO pedigree_stats
                (sire_id, sire_name, course, distance, surface, track_condition,
                 starts, wins, seconds, thirds, win_rate, place_rate, show_rate, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    sire_id, sire_name, course, distance, surface, None,
                    s, w, p, t,
                    round(w / s, 3), round((w + p) / s, 3), round((w + p + t) / s, 3),
                    now,
                ),
            )
        conn.execute(
            "INSERT OR REPLACE INTO fetch_log (target_id, kind, fetched_at) VALUES (?, 'pedigree_stats', ?)",
            (sire_id, now),
        )
    print(
        f"  [ok]   sire {sire_id}: {sire_name or '(名称不明)'} "
        f"{len(agg)} 条件 / 延べ {len(rows)} 走を pedigree_stats に集計"
    )
    return len(agg)


# --------------------------------------------------------------------------- #
def horses_in_race(race_id: str) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT horse_id FROM entries WHERE race_id=?", (race_id,)
        ).fetchall()
    if rows:
        return [r["horse_id"] for r in rows]
    try:
        data = keibalab.fetch_race_result(race_id)
        return [ru["horse_id"] for ru in data.get("runners", [])]
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] {race_id}: 出走馬取得失敗 {e}")
        return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("horse_ids", nargs="*", help="horse_id(10桁)。複数可")
    ap.add_argument("--race", metavar="RACE_ID", help="指定レースの全出走馬の血統取得")
    ap.add_argument("--sire-stats", metavar="SIRE_ID", help="種牡馬の産駒成績集計（ローカル集計）")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    init_db()

    if args.sire_stats:
        fetch_sire_stats(args.sire_stats, args.force)
        return

    targets: list[str] = list(args.horse_ids)
    if args.race:
        targets.extend(horses_in_race(args.race))

    targets = list(dict.fromkeys(targets))
    if not targets:
        ap.error("horse_id / --race / --sire-stats のいずれかが必要")

    saved = 0
    for h in targets:
        try:
            saved += fetch_horse_pedigree(h, args.force)
        except Exception as e:  # noqa: BLE001
            print(f"  [err]  {h}: {e}")
    print(f"完了: {len(targets)} 頭中 {saved} 頭を保存")


if __name__ == "__main__":
    main()
