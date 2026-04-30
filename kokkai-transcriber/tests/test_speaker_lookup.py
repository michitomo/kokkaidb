"""speaker_lookup の単体テスト"""

from __future__ import annotations

from src.models import SpeakerInfo
from src.speaker_lookup import build_lookup, find_by_name


def _speaker(name: str, affiliation: str = "") -> SpeakerInfo:
    return SpeakerInfo(
        name=name,
        affiliation=affiliation,
        role="",
        start_seconds=0.0,
        start_time="00:00",
        duration_minutes=0,
    )


class TestBuildLookup:
    def test_unique_names(self) -> None:
        speakers = [_speaker("田中太郎"), _speaker("佐藤花子")]
        lookup = build_lookup(speakers)
        assert set(lookup.keys()) == {"田中太郎", "佐藤花子"}

    def test_duplicate_names_keep_first(self) -> None:
        first = _speaker("林太郎", "自由民主党")
        second = _speaker("林太郎", "立憲民主党")
        lookup = build_lookup([first, second])
        assert lookup["林太郎"].affiliation == "自由民主党"


class TestFindByName:
    def test_exact_match(self) -> None:
        lookup = build_lookup([_speaker("高市早苗", "自由民主党")])
        result = find_by_name("高市早苗", lookup)
        assert result is not None
        assert result.name == "高市早苗"

    def test_two_char_surname_match(self) -> None:
        lookup = build_lookup([_speaker("赤澤亮正", "経済産業大臣")])
        result = find_by_name("赤澤", lookup)
        assert result is not None
        assert result.name == "赤澤亮正"

    def test_two_char_surname_with_role_suffix(self) -> None:
        """LLM が "高市総理大臣" と返したケース。"""
        lookup = build_lookup([_speaker("高市早苗", "内閣総理大臣")])
        result = find_by_name("高市総理大臣", lookup)
        assert result is not None
        assert result.name == "高市早苗"

    def test_single_char_disabled_for_normalizer(self) -> None:
        lookup = build_lookup([_speaker("林太郎")])
        result = find_by_name("林", lookup, allow_single_char=False)
        assert result is None

    def test_single_char_enabled_for_structurer(self) -> None:
        lookup = build_lookup([_speaker("林太郎")])
        result = find_by_name("林", lookup, allow_single_char=True)
        assert result is not None
        assert result.name == "林太郎"

    def test_ambiguous_two_char_resolved_by_affiliation_hint(self) -> None:
        a = _speaker("赤澤亮正", "経済産業大臣")
        b = _speaker("赤澤花子", "立憲民主党")
        lookup = build_lookup([a, b])
        result = find_by_name("赤澤", lookup, hint_affiliation="立憲民主党")
        assert result is not None
        assert result.name == "赤澤花子"

    def test_ambiguous_falls_back_to_first(self) -> None:
        a = _speaker("赤澤亮正", "経済産業大臣")
        b = _speaker("赤澤花子", "立憲民主党")
        lookup = build_lookup([a, b])
        result = find_by_name("赤澤", lookup)
        assert result is not None
        assert result.name == "赤澤亮正"

    def test_no_match_returns_none(self) -> None:
        lookup = build_lookup([_speaker("田中太郎")])
        assert find_by_name("山田", lookup) is None

    def test_empty_inputs(self) -> None:
        assert find_by_name("", {}) is None
        assert find_by_name("田中太郎", {}) is None
