"""normalize_utterances (Step 5.5) の単体テスト"""

from __future__ import annotations

from src.models import (
    SegmentUtterances,
    SpeakerInfo,
    Utterance,
    UtterancesOutput,
)
from src.normalizer import coerce_role, normalize_utterances
from src.scrapers._role import derive_role


def _speaker(name: str, affiliation: str) -> SpeakerInfo:
    return SpeakerInfo(
        name=name,
        affiliation=affiliation,
        role=derive_role(affiliation),
        start_seconds=0.0,
        start_time="00:00",
        duration_minutes=0,
    )


def _utterance(speaker: str, role: str, text: str = "...") -> Utterance:
    return Utterance(speaker=speaker, role=role, text=text)


def _wrap(seg_speaker: str, seg_affiliation: str, utts: list[Utterance]) -> UtterancesOutput:
    return UtterancesOutput(
        segments=[
            SegmentUtterances(
                segment_index=0,
                segment_speaker=seg_speaker,
                segment_affiliation=seg_affiliation,
                start_seconds=0.0,
                video_url="",
                utterances=utts,
            )
        ]
    )


class TestCoerceRole:
    def test_matched_speaker_overrides_raw(self) -> None:
        matched = _speaker("赤澤亮正", "経済産業大臣")
        assert coerce_role("質疑者", matched) == "答弁者"

    def test_raw_already_canonical(self) -> None:
        assert coerce_role("委員長", None) == "委員長"

    def test_raw_minister_string_coerced(self) -> None:
        assert coerce_role("内閣総理大臣", None) == "答弁者"

    def test_raw_unknown_falls_back(self) -> None:
        assert coerce_role("不明な肩書き", None) == "その他"

    def test_empty_raw_falls_back(self) -> None:
        assert coerce_role("", None) == "その他"


class TestNormalizeUtterances:
    def test_exact_match_preserves_name(self) -> None:
        speakers = [_speaker("高市早苗", "内閣総理大臣")]
        utterances = _wrap(
            "高市早苗",
            "内閣総理大臣",
            [_utterance("高市早苗", "質疑者")],
        )
        result = normalize_utterances(utterances, speakers)
        u = result.segments[0].utterances[0]
        assert u.speaker == "高市早苗"
        assert u.role == "答弁者"
        assert u.unmatched is False

    def test_role_suffix_stripped_to_metadata_name(self) -> None:
        speakers = [_speaker("高市早苗", "内閣総理大臣")]
        utterances = _wrap(
            "高市早苗",
            "内閣総理大臣",
            [_utterance("高市総理大臣", "答弁者")],
        )
        result = normalize_utterances(utterances, speakers)
        assert result.segments[0].utterances[0].speaker == "高市早苗"
        assert result.segments[0].utterances[0].unmatched is False

    def test_unmatched_keeps_raw_speaker(self) -> None:
        speakers = [_speaker("高市早苗", "内閣総理大臣")]
        utterances = _wrap(
            "高市早苗",
            "内閣総理大臣",
            [_utterance("山田次郎", "質疑者")],
        )
        result = normalize_utterances(utterances, speakers)
        u = result.segments[0].utterances[0]
        assert u.speaker == "山田次郎"
        assert u.unmatched is True

    def test_single_char_surname_not_matched(self) -> None:
        speakers = [_speaker("林太郎", "自由民主党")]
        utterances = _wrap(
            "林太郎",
            "自由民主党",
            [_utterance("林", "質疑者")],
        )
        result = normalize_utterances(utterances, speakers)
        assert result.segments[0].utterances[0].unmatched is True

    def test_minister_role_overrides_llm_misclassification(self) -> None:
        speakers = [_speaker("赤澤亮正", "経済産業大臣")]
        utterances = _wrap(
            "赤澤亮正",
            "経済産業大臣",
            [_utterance("赤澤亮正", "質疑者")],
        )
        result = normalize_utterances(utterances, speakers)
        assert result.segments[0].utterances[0].role == "答弁者"
