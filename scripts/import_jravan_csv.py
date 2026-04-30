"""JRA-VAN Data Lab から手動エクスポートした CSV を取り込む。

JRA-VAN Data Lab は有料だがデータ品質・安定性が段違い。
netkeiba スクレイピングの代替・補完として設計。

使用例:
  python scripts/import_jravan_csv.py data/jravan/race_202604.csv
  python scripts/import_jravan_csv.py data/jravan/results_202604.csv --kind results
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect, init_db  # noqa: E402


def detect_kind(path: Path) -> str:
    """ファイル名から取り込み種別を推定。

    'race', 'shutuba' → races/entries
    'result' → results
    'pedigree', 'horse' → horses
    """
    name = path.name.lower()
    if "result" in name:
        return "results"
    if "pedigree" in name or "horse" in name:
        return "horses"
    if "shutuba" in name or "race" in name:
        return "races"
    return "unknown"


def import_csv(path: Path, kind: str) -> int:
    """CSV のスキーマは JRA-VAN Data Lab のエクスポートに依存する。

    TODO: 実運用で初回 CSV を取得した時点でスキーマを確定し、
    ヘッダ → DB カラム のマッピング辞書を本ファイルに固定する。
    """
    if not path.exists():
        raise FileNotFoundError(path)

    print(f"  [todo] {path.name} ({kind}): JRA-VAN CSV スキーマ未確定。初回エクスポート後に実装")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="CSV ファイルパス")
    ap.add_argument("--kind", choices=["races", "results", "horses", "auto"], default="auto")
    args = ap.parse_args()

    init_db()

    total = 0
    for p in args.paths:
        path = Path(p)
        kind = detect_kind(path) if args.kind == "auto" else args.kind
        if kind == "unknown":
            print(f"  [warn] {path.name}: 種別が判定できず、--kind を指定してください")
            continue
        try:
            total += import_csv(path, kind)
        except Exception as e:  # noqa: BLE001
            print(f"  [err]  {path.name}: {e}")

    print(f"完了: {len(args.paths)} ファイル、{total} 行")


if __name__ == "__main__":
    main()
