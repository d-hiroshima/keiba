"""JRA-VAN Data Lab から手動エクスポートした CSV を取り込む。

⚠️ **未実装スタブ**。CSV のカラム構成はエクスポート元ツール（TARGET 等）に依存するため、
初回の実 CSV を取得した時点でヘッダ → DB カラムのマッピングを確定して実装する
（推測でマッピングすると静かに誤データが入るため、それまでは取り込まずエラー終了する）。

位置づけ: keibalab スクレイピングの補完。規約クリーンな一括バックフィル
（過去重賞の大量蓄積）が必要になったらこの経路を使う。

使用例（実装後）:
  python3 scripts/import_jravan_csv.py data/jravan/race_202604.csv
  python3 scripts/import_jravan_csv.py data/jravan/results_202604.csv --kind results
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import init_db  # noqa: E402


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

    raise NotImplementedError(
        f"{path.name} ({kind}): JRA-VAN CSV のマッピングは未実装（スタブ）。"
        "初回エクスポートのヘッダを確認してから実装する — 黙って 0 行取り込み成功に見せない"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="CSV ファイルパス")
    ap.add_argument("--kind", choices=["races", "results", "horses", "auto"], default="auto")
    args = ap.parse_args()

    init_db()

    total = 0
    failures = 0
    for p in args.paths:
        path = Path(p)
        kind = detect_kind(path) if args.kind == "auto" else args.kind
        if kind == "unknown":
            failures += 1
            print(f"  [err]  {path.name}: 種別が判定できず、--kind を指定してください")
            continue
        try:
            total += import_csv(path, kind)
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"  [err]  {path.name}: {e}")

    print(f"完了: {len(args.paths)} ファイル、{total} 行 / 失敗 {failures}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
