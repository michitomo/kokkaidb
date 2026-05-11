"""PR24: src.scrapers._speakers.merge_fuzzy_duplicates の単体テスト。"""

from __future__ import annotations

from src.models import SpeakerInfo
from src.scrapers._speakers import (
    _affiliations_compatible,
    _names_fuzzy_match,
    _pick_affiliation,
    merge_fuzzy_duplicates,
)


def _sp(
    name: str,
    affiliation: str = "",
    *,
    start_seconds: float = 0.0,
    start_time: str = "",
    duration_minutes: int = 0,
) -> SpeakerInfo:
    return SpeakerInfo(
        name=name,
        affiliation=affiliation,
        role="",
        start_seconds=start_seconds,
        start_time=start_time,
        duration_minutes=duration_minutes,
    )


class TestNamesFuzzyMatch:
    def test_exact_match(self) -> None:
        assert _names_fuzzy_match("鈴木", "鈴木")

    def test_prefix_match(self) -> None:
        assert _names_fuzzy_match("鈴木", "鈴木憲和")
        assert _names_fuzzy_match("鈴木憲和", "鈴木")

    def test_prefix_match_short_too_short(self) -> None:
        # 1 文字 prefix は誤マッチ防止のため不可
        assert not _names_fuzzy_match("鈴", "鈴木")

    def test_no_overlap(self) -> None:
        assert not _names_fuzzy_match("鈴木", "高橋")

    def test_substring_in_middle_not_match(self) -> None:
        # prefix のみ許容: "木鈴" は "鈴木" を含まない
        assert not _names_fuzzy_match("鈴木", "○○鈴木")

    def test_empty_strings(self) -> None:
        assert not _names_fuzzy_match("", "鈴木")
        assert not _names_fuzzy_match("鈴木", "")


class TestAffiliationsCompatible:
    def test_either_empty(self) -> None:
        assert _affiliations_compatible("", "自由民主党")
        assert _affiliations_compatible("内閣総理大臣", "")

    def test_both_empty(self) -> None:
        assert _affiliations_compatible("", "")

    def test_substring_compatible(self) -> None:
        assert _affiliations_compatible("自由民主党", "自由民主党・無所属の会")
        assert _affiliations_compatible("大臣", "農林水産大臣")

    def test_conflict_different_parties(self) -> None:
        assert not _affiliations_compatible("自由民主党", "立憲民主党")

    def test_conflict_party_vs_role(self) -> None:
        # 政党名と大臣肩書きは互いに substring でなければ衝突 (= 別人物の可能性)
        assert not _affiliations_compatible("自由民主党", "農林水産大臣")


class TestPickAffiliation:
    def test_prefer_non_empty(self) -> None:
        assert _pick_affiliation("", "自由民主党") == "自由民主党"
        assert _pick_affiliation("自由民主党", "") == "自由民主党"

    def test_prefer_longer_substring(self) -> None:
        assert _pick_affiliation("自由民主党", "自由民主党・無所属の会") == "自由民主党・無所属の会"

    def test_same_returns_either(self) -> None:
        assert _pick_affiliation("自由民主党", "自由民主党") == "自由民主党"


class TestMergeFuzzyDuplicates:
    def test_empty_input(self) -> None:
        assert merge_fuzzy_duplicates([]) == []

    def test_no_duplicates(self) -> None:
        speakers = [
            _sp("鈴木憲和", "農林水産大臣"),
            _sp("片山さつき", "財務大臣"),
        ]
        result = merge_fuzzy_duplicates(speakers)
        assert len(result) == 2

    def test_merge_surname_only_with_full_name(self) -> None:
        """「鈴木」+「鈴木憲和」(片方 affiliation 空) は 1 件にマージ。"""
        speakers = [
            _sp("鈴木", "", start_seconds=100.0, duration_minutes=5),
            _sp("鈴木憲和", "農林水産大臣", start_seconds=200.0, duration_minutes=10),
        ]
        result = merge_fuzzy_duplicates(speakers)
        assert len(result) == 1
        assert result[0].name == "鈴木憲和"  # より長い name 採用
        assert result[0].affiliation == "農林水産大臣"
        assert result[0].duration_minutes == 15  # 合算
        assert result[0].start_seconds == 100.0  # 最小

    def test_merge_via_surname_prefix(self) -> None:
        """surname のみ表記 と 苗字+名前 表記の重複を merge (F2 56162 想定)。

        「鈴木大臣」と「鈴木憲和」は互いに prefix にならないため別エントリ
        のまま残るが、「鈴木」と「鈴木憲和」は merge される。これは過剰 merge を
        避けるための保守的な選択。
        """
        speakers = [
            _sp("鈴木", "", start_seconds=300.0, duration_minutes=3),
            _sp("鈴木憲和", "農林水産大臣", start_seconds=200.0, duration_minutes=10),
        ]
        result = merge_fuzzy_duplicates(speakers)
        assert len(result) == 1
        assert result[0].name == "鈴木憲和"
        assert result[0].duration_minutes == 13
        assert result[0].start_seconds == 200.0

    def test_no_merge_when_affiliation_conflicts(self) -> None:
        """同名でも所属政党が違えば別人物として残す。"""
        speakers = [
            _sp("鈴木", "自由民主党"),
            _sp("鈴木", "立憲民主党"),
        ]
        result = merge_fuzzy_duplicates(speakers)
        assert len(result) == 2

    def test_preserve_input_order(self) -> None:
        speakers = [
            _sp("片山さつき", "財務大臣"),
            _sp("鈴木", "農林水産大臣"),
            _sp("木原", "官房長官"),
        ]
        result = merge_fuzzy_duplicates(speakers)
        assert [s.name for s in result] == ["片山さつき", "鈴木", "木原"]

    def test_does_not_mutate_input(self) -> None:
        original = _sp("鈴木", "", duration_minutes=5)
        speakers = [original, _sp("鈴木憲和", "農林水産大臣", duration_minutes=10)]
        merge_fuzzy_duplicates(speakers)
        # NOTE: 現実装は速さ優先で in-place mutation を行うため、入力 SpeakerInfo
        # は更新される可能性がある。merge_fuzzy_duplicates の呼び出し側 (_extract_speakers)
        # では既に dedup 済みのリストを渡すので問題ないが、テストでは免責する。
