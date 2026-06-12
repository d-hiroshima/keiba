"""エージェント／統合出力が `docs/output-schema.md` に準拠しているか検証する。

使用例:
  python scripts/validate_output.py output.md --type pedigree
  python scripts/validate_output.py integrated.md --type integrated
  python scripts/validate_output.py output.md            # ヘッダから自動判別

非ゼロ終了コード = スキーマ違反あり。CI と Slack bot orchestrator から呼ぶ想定。
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_SECTIONS: dict[str, list[str]] = {
    "pedigree": [
        "全頭評価サマリ",
        "詳細評価",
        "自由記述",
    ],
    "track": [
        "全頭評価サマリ",
        "想定ペース全体像",
        "詳細評価",
    ],
    "race-context": [
        "全頭の展開恩恵度",
        "有利不利マトリクス",
        "観察すべき次のデータポイント",
    ],
    "macro-scout": [
        "天候・馬場予想",
        "当日の馬場発表",
        "オッズ",
        "馬体重",
        "周辺重賞",
        "判定の前提となる重要トリガー",
    ],
    "devils": [
        "本命論の要約",
        "全頭評価サマリ横断レビュー",
        "弱点",
        "外れるシナリオ",
        "データソースの限界",
        "全頭への補正提案",
        "結論",
    ],
    "integrated": [
        "データ取得状況",
        "エージェント別結論サマリ",
        "全頭評価サマリ",
        "統合判断",
        "想定ペース・展開",
        "買い目",
        "リスクと反証条件",
        "次に観察すべきデータ",
    ],
}

REQUIRED_COLUMNS: dict[str, list[str]] = {
    "pedigree": ["馬番", "馬名", "父", "母父", "強気度", "確信度", "キー論点"],
    "track": [
        "馬番", "馬名", "持ち時計", "想定脚質", "想定位置取り",
        "コース適性", "騎手", "強気度", "確信度",
    ],
    "race-context": [
        "馬番", "馬名", "想定脚質", "想定位置取り",
        "展開恩恵度", "強気度", "確信度",
    ],
    "macro-scout": ["馬番", "馬名", "単勝", "人気"],
    "devils": ["馬番", "馬名", "devils 補正", "補正理由"],
    "integrated": [
        "馬番", "馬名", "想定人気", "pedigree", "track",
        "race-context", "devils", "総合", "選定",
    ],
}

# 統合出力の選定記号値域
SELECTION_TOKENS = {"◎", "○", "▲", "△", "▽", "-", "—"}


@dataclass
class Violation:
    severity: str  # "error" | "warn"
    message: str

    def format(self) -> str:
        tag = "ERROR" if self.severity == "error" else "WARN "
        return f"[{tag}] {self.message}"


@dataclass
class ValidationResult:
    target_type: str
    violations: list[Violation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(v.severity == "error" for v in self.violations)


def detect_type(text: str) -> str | None:
    """ヘッダ `## <agent> — race:` または `# レース予想:` から型を判別。"""
    m = re.search(r"^##\s+([a-z\-]+)\s*—\s*race:", text, re.MULTILINE)
    if m:
        name = m.group(1)
        if name == "pedigree-analyst":
            return "pedigree"
        if name == "track-analyst":
            return "track"
        if name == "race-context-analyst":
            return "race-context"
        if name == "macro-scout":
            return "macro-scout"
        if name == "devils-advocate":
            return "devils"
    if re.search(r"^#\s+レース予想:", text, re.MULTILINE):
        return "integrated"
    return None


def _check_sections(text: str, required: list[str]) -> list[Violation]:
    """必須セクションが（見出し or 太字 or 表頭文字列で）登場するか確認。"""
    out: list[Violation] = []
    for section in required:
        # `### 全頭評価...` / `**全頭評価...**` / 平文どれでも検出する
        pattern = re.escape(section)
        if not re.search(pattern, text):
            out.append(Violation("error", f"必須セクション欠落: {section}"))
    return out


def _check_table_columns(text: str, required: list[str]) -> list[Violation]:
    """少なくとも1つの表ヘッダ行に必須カラムがすべて含まれているか確認。"""
    out: list[Violation] = []
    table_headers = re.findall(r"^\|(.+)\|\s*$", text, re.MULTILINE)
    if not table_headers:
        out.append(Violation("error", "表が1つも見つからない"))
        return out

    for missing_check_col in required:
        # どこかの表ヘッダにそのカラムが含まれていれば OK
        found = any(missing_check_col in h for h in table_headers)
        if not found:
            out.append(Violation("error", f"必須カラム欠落: {missing_check_col}"))
    return out


def _check_value_ranges(text: str) -> list[Violation]:
    """強気度・確信度・選定記号の値域を表セルから抜きとって確認。"""
    out: list[Violation] = []

    # 強気度: -5..+5（表セル内に出る数字を緩く拾う）
    bullish_matches = re.findall(r"(?<![0-9])([+\-]?\d+)\s*\|", text)
    for v in bullish_matches:
        try:
            n = int(v)
        except ValueError:
            continue
        if -10 <= n <= 10 and not (-5 <= n <= 5):
            out.append(Violation("warn", f"強気度らしき値が値域外: {n}（-5〜+5）"))

    # 選定記号
    sel_matches = re.findall(r"\|\s*([◎○▲△▽\-—])\s*\|", text)
    for s in sel_matches:
        if s not in SELECTION_TOKENS:
            out.append(Violation("warn", f"選定記号が値域外: {s}"))
    return out


def _check_integrated_betting(text: str) -> list[Violation]:
    """統合出力の買い目セクションで、予算指定時に合計欄があるか緩く確認。"""
    out: list[Violation] = []
    if "買い目" not in text:
        return out
    # 予算指定の痕跡: `XXXX円` がセクション見出し近辺にあれば
    if re.search(r"買い目.*\d{3,5}\s*円", text):
        if "**合計**" not in text and "合計" not in text:
            out.append(Violation(
                "warn",
                "買い目セクションに予算指定の痕跡があるが「合計」欄が見当たらない",
            ))
    return out


def _check_failure_markers(text: str) -> list[Violation]:
    """データ取得失敗の明示（空欄禁止）を緩く確認。空のセル（| | や | |）が多すぎる場合に警告。"""
    out: list[Violation] = []
    empty_cells = len(re.findall(r"\|\s{2,}\|", text))
    if empty_cells > 5:
        out.append(Violation(
            "warn",
            f"空セルらしき箇所が {empty_cells} 個。「取得失敗」「N=不明」等で明示推奨",
        ))
    return out


# --------------------------------------------------------------------------- #
# 分析的落とし穴の検出（2026 日本ダービー大外しの反省から追加）
# スキーマ(構造)ではなく、過去に大外しした「中身/プロセス」の典型を warn で拾う。
# heuristic ゆえ severity は warn（--strict で失敗扱いにできる）。
# 各チェックは対象テキストに該当文脈が無ければ no-op。
# --------------------------------------------------------------------------- #
_EXEMPTION_WORDS = (
    "休み明け", "ぶっつけ", "展開不利", "展開待ち", "距離不適", "距離延長",
    "出遅れ", "度外視", "位置取り", "割引", "不利", "トリップ",
)
_ALT_PACE_WORDS = (
    "代替隊列", "別馬が逃げ", "2パターン", "２パターン", "2シナリオ", "２シナリオ",
    "シナリオ", "に振れれば", "に振れると", "崩れた場合", "崩れれば", "もう一方",
)
_LIGHT_WORDS = ("軽い", "小柄", "非力", "体が細", "細い", "馬体不安", "体重不安", "華奢")
_SINGLE_AXIS_WORDS = ("軸1頭", "軸１頭", "1頭ながし", "１頭ながし", "1頭流し", "一頭軸", "軸ながし")
_HEDGE_WORDS = ("軸2頭", "軸２頭", "2頭軸", "フォーメーション", "ボックス", "押さえ", "保険")
_OPEN_RACE_WORDS = ("1強不在", "一強不在", "妙味レース", "勝ち切れない", "勝ち味", "複勝圏の堅さ", "展開待ち")


def _check_pace_scenarios(text: str) -> list[Violation]:
    """想定ペースが単一前提で、代替隊列/2シナリオの記載が無い場合に warn。"""
    out: list[Violation] = []
    if "ペース" not in text and "展開" not in text:
        return out
    if not any(w in text for w in _ALT_PACE_WORDS):
        out.append(Violation(
            "warn",
            "想定ペースが単一前提の可能性。2シナリオ(確信度付き)＋代替隊列"
            "(本命逃げ馬が控える/別馬が逃げる)を併記推奨 [2026ダービー反省]",
        ))
    return out


def _check_cut_exemption(text: str) -> list[Violation]:
    """前走着順を理由に強い消しをしている行に、免責チェックの語が無ければ warn（行単位）。"""
    out: list[Violation] = []
    for line in text.splitlines():
        if "着" not in line:
            continue
        strong_cut = ("消し" in line) or bool(re.search(r"(?<![0-9])-\s*[345](?=\s*\||\s|$)", line))
        if strong_cut and re.search(r"\d+\s*着", line) and not any(w in line for w in _EXEMPTION_WORDS):
            out.append(Violation(
                "warn",
                f"消し評価が前走着順依存の可能性: 「{line.strip()[:36]}…」"
                "免責(休み明け/展開不利/距離不適/出遅れ)を確認 [2026ダービー反省]",
            ))
    return out[:3]  # 多すぎる時は先頭3件に絞る


def _check_single_axis(text: str) -> list[Violation]:
    """『1強不在/妙味/勝ち切れない軸』と自認しつつ軸1頭流しに依存していれば warn。"""
    out: list[Violation] = []
    if "買い目" not in text:
        return out
    if (
        any(w in text for w in _OPEN_RACE_WORDS)
        and any(w in text for w in _SINGLE_AXIS_WORDS)
        and not any(w in text for w in _HEDGE_WORDS)
    ):
        out.append(Violation(
            "warn",
            "『1強不在/妙味/勝ち切れない軸』と自認しつつ軸1頭流しに依存。"
            "軸を割る(2頭軸/フォーメーション)or人気サイドへの押さえを検討 [2026ダービー反省]",
        ))
    return out


def _check_weight_threshold(text: str) -> list[Violation]:
    """馬体重 460kg 以上を『軽い/小柄/不安』と減点していれば warn（閾値は460切り）。"""
    out: list[Violation] = []
    # 体重表記は "466(+8)" / "448kg" 等。斤量(57.0)誤検出を避け kg/キロ/括弧を要求。
    for m in re.finditer(r"(4[6-9]\d|5\d\d)\s*(?:kg|キロ|[\(（])", text):
        w = int(m.group(1))
        window = text[max(0, m.start() - 20): m.end() + 20]
        if any(lw in window for lw in _LIGHT_WORDS):
            out.append(Violation(
                "warn",
                f"馬体重{w}kgを『軽い/小柄/不安』扱いの可能性。タフコース不安の閾値は"
                "460kg切り(tokyo-2400 §4)。460以上で減点しない [2026ダービー反省]",
            ))
            break
    return out


def _check_analysis_pitfalls(text: str, target_type: str) -> list[Violation]:
    """型に応じた分析的落とし穴チェックを集約。"""
    out: list[Violation] = []
    if target_type in ("integrated", "race-context"):
        out.extend(_check_pace_scenarios(text))
    if target_type in ("integrated", "devils"):
        out.extend(_check_cut_exemption(text))
    if target_type == "integrated":
        out.extend(_check_single_axis(text))
    if target_type in ("integrated", "track", "pedigree", "macro-scout"):
        out.extend(_check_weight_threshold(text))
    return out


def validate(text: str, target_type: str | None = None) -> ValidationResult:
    detected = target_type or detect_type(text)
    if detected is None:
        return ValidationResult(
            target_type="unknown",
            violations=[Violation("error", "出力タイプを判別できない（ヘッダ未検出）")],
        )
    if detected not in REQUIRED_SECTIONS:
        return ValidationResult(
            target_type=detected,
            violations=[Violation("error", f"未知のターゲット型: {detected}")],
        )

    result = ValidationResult(target_type=detected)
    result.violations.extend(_check_sections(text, REQUIRED_SECTIONS[detected]))
    result.violations.extend(_check_table_columns(text, REQUIRED_COLUMNS[detected]))
    result.violations.extend(_check_value_ranges(text))
    result.violations.extend(_check_failure_markers(text))
    if detected == "integrated":
        result.violations.extend(_check_integrated_betting(text))
    # 分析的落とし穴（2026ダービー反省）。スキーマ違反とは別レイヤの warn。
    result.violations.extend(_check_analysis_pitfalls(text, detected))
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="出力スキーマ検証")
    ap.add_argument("file", type=Path, help="検証対象の Markdown ファイル")
    ap.add_argument(
        "--type",
        choices=list(REQUIRED_SECTIONS.keys()),
        help="ターゲット型（省略時はヘッダから自動判別）",
    )
    ap.add_argument("--strict", action="store_true", help="warn も失敗扱い")
    args = ap.parse_args()

    text = args.file.read_text(encoding="utf-8")
    result = validate(text, args.type)

    print(f"target: {result.target_type}")
    if not result.violations:
        print("[OK] スキーマ違反なし")
        return 0

    for v in result.violations:
        print(v.format())

    has_error = any(v.severity == "error" for v in result.violations)
    has_warn = any(v.severity == "warn" for v in result.violations)
    if has_error:
        return 1
    if has_warn and args.strict:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
