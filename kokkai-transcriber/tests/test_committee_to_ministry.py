"""committee_to_ministry の単体テスト"""

from __future__ import annotations

from src.committee_to_ministry import (
    COMMITTEE_TO_MINISTRY,
    filter_laws_for_committee,
)


def test_known_committee_filters_to_ministry() -> None:
    laws = "\n".join(
        [
            "law_001: [閣法] 健康保険法改正 | 厚生労働省 | ...",
            "law_002: [閣法] 道路運送法改正 | 国土交通省 | ...",
            "law_003: [閣法] 介護保険法改正 | 厚生労働省 | ...",
        ]
    )
    result = filter_laws_for_committee(laws, "厚生労働委員会")
    lines = result.splitlines()
    assert len(lines) == 2
    assert all("厚生労働省" in line for line in lines)


def test_committee_with_multiple_ministries() -> None:
    laws = "\n".join(
        [
            "law_001: [閣法] 道路運送法改正 | 国土交通省 | ...",
            "law_002: [閣法] 銀行法改正 | 金融庁 | ...",
            "law_003: [閣法] 所得税法改正 | 財務省 | ...",
        ]
    )
    result = filter_laws_for_committee(laws, "財務金融委員会")
    assert len(result.splitlines()) == 2


def test_unknown_committee_passes_through() -> None:
    laws = "law_001: [閣法] foo | 厚生労働省 | ..."
    assert filter_laws_for_committee(laws, "謎の特別委員会") == laws


def test_passthrough_when_committee_has_no_ministry_filter() -> None:
    laws = "law_001: [閣法] foo | 厚生労働省 | ..."
    assert filter_laws_for_committee(laws, "本会議") == laws


def test_no_match_falls_back_to_full_list() -> None:
    laws = "law_001: [閣法] 道路運送法改正 | 国土交通省 | ..."
    result = filter_laws_for_committee(laws, "厚生労働委員会")
    assert result == laws


def test_empty_input_returns_empty() -> None:
    assert filter_laws_for_committee("", "厚生労働委員会") == ""


def test_mapping_includes_major_committees() -> None:
    expected = {
        "厚生労働委員会",
        "外務委員会",
        "経済産業委員会",
        "法務委員会",
        "本会議",
    }
    assert expected.issubset(set(COMMITTEE_TO_MINISTRY.keys()))
