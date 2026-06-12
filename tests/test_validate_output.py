"""validate_output.py の検証ロジックのテスト（偽陽性の回帰防止を含む）。"""

from __future__ import annotations

from validate_output import detect_type, validate

INTEGRATED_OK = """# レース予想: 202606010511 テスト記念（tokyo 1600m turf, GIII）
日付: 2026-06-01（発走 15:40） / 出走 18 頭
取得日時: 2026-06-01 12:00 JST

## データ取得状況
- 出馬表: 全頭確定（data/race.db）

## エージェント別結論サマリ
| エージェント | 強気度 | 確信度 | キー論点 |
|---|---|---|---|
| pedigree | +3 | 4 | 父系が同条件に合う |

## 全頭評価サマリ（必須・出走全頭）
| 馬番 | 馬名 | 想定人気 | pedigree | track | race-context | devils | 総合 | 選定 | キー論点 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | アルファ | 2 | +3 | +2 | +1 | -1 | +2 | ◎ | 同条件で堅実 |
| 18 | オメガ | 10 | 0 | -1 | 0 | 0 | 0 | - | 大外で割引 |

## 統合判断
- 本命: アルファ（2シナリオで上位）

## 想定ペース・展開
- M 想定（確信度3）/ 代替隊列: 別馬が逃げるシナリオも併記

## 買い目（参考）
| 買い目 | 推定オッズ | 投資額 | 想定払戻 |
|---|---|---|---|
| 1-18 | 10 | 300 円 | 3000 円 |
| **合計** | | 300 円 | |

## リスクと反証条件
- 雨で馬場急変したら見送り

## 次に観察すべきデータ
- 当日の馬場発表

*本予想は賭博助言ではありません。*
"""


def test_integrated_clean_passes():
    result = validate(INTEGRATED_OK, "integrated")
    errors = [v for v in result.violations if v.severity == "error"]
    assert errors == []


def test_no_false_positive_on_horse_numbers():
    """馬番 6-18 を強気度と誤認して warn を出さない（旧実装の偽陽性回帰テスト）。"""
    result = validate(INTEGRATED_OK, "integrated")
    assert not any("強気度らしき値が値域外" in v.message for v in result.violations)


def test_bullishness_out_of_range_detected():
    text = INTEGRATED_OK.replace("| 1 | アルファ | 2 | +3 |", "| 1 | アルファ | 2 | +7 |")
    result = validate(text, "integrated")
    assert any("強気度らしき値が値域外: 7" in v.message for v in result.violations)


def test_detect_type_macro_scout_and_races_form():
    assert detect_type("## macro-scout — race: 202606010511\n") == "macro-scout"
    assert detect_type("## macro-scout — races: [202606010511, 202606010512]\n") == "macro-scout"
    assert detect_type("## pedigree-analyst — race: 202606010511\n") == "pedigree"
    assert detect_type("# レース予想: 202606010511\n") == "integrated"


def test_missing_datetime_is_error_for_agents():
    text = """## pedigree-analyst — race: 202606010511

### 全頭評価サマリ（出走全頭）
| 馬番 | 馬名 | 父 | 母父 | 同条件父系勝率 | 強気度 | 確信度 | キー論点 |
|---|---|---|---|---|---|---|---|
| 1 | アルファ | 架空父 | 架空母父 | 20%(N=12) | +3 | 4 | 適合 |

### 詳細評価
...

### 自由記述
...
"""
    result = validate(text, "pedigree")
    assert any(
        v.severity == "error" and "取得日時" in v.message for v in result.violations
    )


def test_n_zero_fabrication_warned():
    text = INTEGRATED_OK + "\n父系成績: 15%(N=0)\n"
    result = validate(text, "integrated")
    assert any("N=0 なのに具体的勝率" in v.message for v in result.violations)
