"""validate_output.py の検証ロジックのテスト（偽陽性の回帰防止を含む）。"""

from __future__ import annotations

import validate_output
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


def test_marked_horse_missing_from_bets_warns():
    """印を付けた馬が買い目に1点も無ければ warn [2026セントライト記念反省]。"""
    text = """# レース予想: 202609130611 テスト

## 全頭評価サマリ
| 馬番 | 馬名 | 総合 | 選定 |
|---|---|---|---|
| 6 | アルファ | +4 | ◎ |
| 7 | ベータ | +1 | ▽ |
| 8 | ガンマ | +3 | ○ |

## 買い目（参考）
### 三連複 200円
| 買い目 | 投資額 |
|---|---|
| 6-8-9 | 100 円 |
| 6-8-10 | 100 円 |
"""
    vs = validate_output._check_marked_horse_in_bets(text)
    assert len(vs) == 1
    assert "▽7" in vs[0].message


def test_marked_horses_all_in_bets_no_warn():
    text = """# レース予想: 202609130611 テスト

## 全頭評価サマリ
| 馬番 | 馬名 | 総合 | 選定 |
|---|---|---|---|
| 6 | アルファ | +4 | ◎ |
| 7 | ベータ | +1 | ▽ |

## 買い目（参考）
### ワイド 100円
| 買い目 | 投資額 |
|---|---|
| 6-7 | 100 円 |
"""
    assert validate_output._check_marked_horse_in_bets(text) == []


_ARC_MARKS = """# レース予想: 202610049905 テスト

## 全頭評価サマリ
| 馬番 | 馬名 | 総合 | 選定 |
|---|---|---|---|
| 1 | アルファ | +3 | ◎ |
| 7 | ベータ | +1 | ▽ |
| 15 | ガンマ | +2 | ○ |

## 買い目（参考）
"""


def test_marked_horse_only_in_trio_warns_when_pairs_bought():
    """2頭券を買いつつ印馬が三連複1点のみなら warn [2026凱旋門賞反省]。"""
    text = _ARC_MARKS + """### ワイド 200円
| 買い目 | 投資額 |
|---|---|
| 1-15 | 100 円 |
### 三連複 100円
| 買い目 | 投資額 |
|---|---|
| 1-7-15 | 100 円 |
"""
    vs = validate_output._check_marked_horse_only_in_trio(text)
    assert len(vs) == 1
    assert "▽7" in vs[0].message


def test_marked_horse_in_pair_no_warn():
    text = _ARC_MARKS + """### ワイド 200円
| 買い目 | 投資額 |
|---|---|
| 1-15 | 100 円 |
| 1-7 | 100 円 |
### 三連複 100円
| 買い目 | 投資額 |
|---|---|
| 1-7-15 | 100 円 |
"""
    assert validate_output._check_marked_horse_only_in_trio(text) == []


def test_trio_only_plan_not_flagged():
    """三連系だけの買い方はユーザー選択なので対象外。"""
    text = _ARC_MARKS + """### 三連複 100円
| 買い目 | 投資額 |
|---|---|
| 1-7-15 | 100 円 |
"""
    assert validate_output._check_marked_horse_only_in_trio(text) == []


def test_pace_without_front_runner_warns():
    """ペースに触れつつ逃げ馬の記述が無ければ warn [2026オールカマー反省]。"""
    text = "## 想定ペース・展開\n想定ペースは Sl。\n\n## 買い目（参考）\n| 買い目 | 投資額 |\n|---|---|\n| 1-2 | 100 円 |\n"
    vs = validate_output._check_front_runner_named(text)
    assert len(vs) == 1
    assert "逃げ馬" in vs[0].message


def test_pace_with_front_runner_no_warn():
    text = "## 想定ペース・展開\n想定ペースは Sl。11番が逃げ、2番が番手。\n\n## 買い目（参考）\n| 買い目 | 投資額 |\n|---|---|\n| 1-2 | 100 円 |\n"
    assert validate_output._check_front_runner_named(text) == []


def test_unscoreable_bet_table_is_error():
    # 2026秋華賞: 採点器が読めない買い目表は、採点が黙って投資 0 円になる
    md = "## 買い目（参考）\n\n### 馬連 1,000円\n| # | 組 | 金 |\n|---|---|---|\n| 1 | 3-8 | 百 |\n"
    msgs = [v.message for v in validate_output._check_bets_scoreable(md) if v.severity == "error"]
    assert any("採点器" in m for m in msgs)


def test_scoreable_bet_table_passes():
    md = (
        "## 買い目（参考）\n\n### 馬連 200円\n| 買い目 | 推定オッズ | 投資額 | 想定払戻 |\n"
        "|---|---|---|---|\n| 3-8 | 5倍 | 100 円 | 500 円 |\n| 8-13 | 4倍 | 100 円 | 400 円 |\n"
    )
    assert validate_output._check_bets_scoreable(md) == []


_SUMMARY = (
    "## 全頭評価サマリ\n"
    "| 馬番 | 馬名 | 想定人気 | pedigree | track | race-context | devils | 総合 | 選定 | キー論点 |\n"
    "|---|---|---|---|---|---|---|---|---|---|\n"
    "| 1 | エー | 7 (30.9) | 0 | 0 | +2 | +2 | +1 | - | {key1} |\n"
    "| 3 | シー | 4 (14.9) | 0 | 0 | 0 | 0 | +2 | ○ | x |\n"
    "| 4 | ディー | 6 (24.6) | 0 | 0 | 0 | 0 | +2 | ▲ | x |\n"
    "| 8 | エイト | 1 (1.4) | 0 | 0 | 0 | 0 | +4 | ◎ | x |\n"
)


def test_positive_unmarked_warns_unless_ev_stated():
    # 2026秋華賞: 総合+1・無印の 1 ギャラボーグが2着
    md = _SUMMARY.format(key1="休み明け＝割引")
    assert any("無印" in v.message for v in validate_output._check_positive_unmarked(md))
    md_ev = _SUMMARY.format(key1="EV 0.4 で閾値割れ")
    assert validate_output._check_positive_unmarked(md_ev) == []


def _bets(rows):
    body = "".join(f"| {c} | - | 100 円 | - |\n" for c in rows)
    return "\n## 買い目（参考）\n\n### 馬連 1,000円\n| 買い目 | 推定オッズ | 投資額 | 想定払戻 |\n|---|---|---|---|\n" + body


def test_box_with_heavy_favorite_warns():
    md = _SUMMARY.format(key1="x") + _bets(["3-4", "3-8", "4-8"])  # 3点中1点が◎抜き → 半数未満
    assert validate_output._check_box_with_heavy_favorite(md) == []
    md = _SUMMARY.format(key1="x") + _bets(["3-4", "1-3", "4-8", "1-4"])  # 4点中3点が◎抜き
    assert any("◎8" in v.message for v in validate_output._check_box_with_heavy_favorite(md))


def test_box_check_ignores_axis_flow():
    # 2026神戸新聞杯: 「軸1 — 相手5頭BOX」と書いた1頭軸流しは全点◎入り → warn しない
    md = _SUMMARY.format(key1="x") + _bets(["3-8", "4-8", "1-8"])
    assert validate_output._check_box_with_heavy_favorite(md) == []


def _judgement(conf):
    return f"\n## 統合判断\n- ◎ 8: 本命\n- **確信度: {conf}**\n"


def test_pairs_all_share_axis_warns_when_confidence_low():
    # 2026菊花賞: ◎8(1.8倍)が14着。2頭券20点すべてが8軸で、○▲▽の3頭で決着したのに0円
    md = _SUMMARY.format(key1="x") + _judgement(3) + _bets(["3-8", "4-8", "1-8", "2-8", "5-8"])
    msgs = [v.message for v in validate_output._check_pairs_all_share_axis(md)]
    assert any("すべてが 8 を含む" in m for m in msgs)


def test_pairs_all_share_axis_silent_when_hedge_exists_or_confident():
    md = _SUMMARY.format(key1="x") + _judgement(3) + _bets(["3-8", "4-8", "1-8", "2-8", "3-4"])
    assert validate_output._check_pairs_all_share_axis(md) == []  # ◎抜きの 3-4 が1点ある
    md = _SUMMARY.format(key1="x") + _judgement(4) + _bets(["3-8", "4-8", "1-8", "2-8", "5-8"])
    assert validate_output._check_pairs_all_share_axis(md) == []  # 確信度4以上は対象外
    md = _SUMMARY.format(key1="x") + _judgement(3) + _bets(["3-8", "4-8"])
    assert validate_output._check_pairs_all_share_axis(md) == []  # 4点未満は対象外


def _two_types(wide_rows, umaren_rows):
    head = "| 買い目 | 推定オッズ | 投資額 | 想定払戻 |\n|---|---|---|---|\n"
    w = "".join(f"| {c} | - | 100 円 | - |\n" for c in wide_rows)
    u = "".join(f"| {c} | - | 100 円 | - |\n" for c in umaren_rows)
    return f"\n## 買い目（参考）\n\n### ワイド 1,000円\n{head}{w}\n### 馬連 1,000円\n{head}{u}"


def test_marked_favorite_split_across_bet_types_warns():
    # 2026マイルCS: △1（4人気）を馬連BOXだけに入れ 1着。ワイド 1-2 / 1-14 を取り逃した
    md = _SUMMARY.format(key1="x") + _two_types(["4-8"], ["3-8", "4-8"])  # ○3（4人気）が馬連のみ
    msgs = [v.message for v in validate_output._check_marked_favorite_split_across_bet_types(md)]
    assert any("○3" in m and "umaren" in m for m in msgs)


def test_marked_favorite_split_silent_when_in_both_or_single_type():
    md = _SUMMARY.format(key1="x") + _two_types(["3-8", "4-8"], ["3-8", "4-8"])
    assert validate_output._check_marked_favorite_split_across_bet_types(md) == []
    # ▲4 は6番人気なので片方だけでも対象外
    md = _SUMMARY.format(key1="x") + _two_types(["3-8"], ["3-8", "4-8"])
    assert validate_output._check_marked_favorite_split_across_bet_types(md) == []
    md = _SUMMARY.format(key1="x") + _bets(["3-8", "4-8"])  # 券種が1つだけ
    assert validate_output._check_marked_favorite_split_across_bet_types(md) == []
