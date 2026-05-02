"""scrapers/_session_kind.detect_session_kind の単体テスト"""

from __future__ import annotations

from src.models import SpeakerInfo
from src.scrapers._session_kind import detect_session_kind


def _speaker(role: str, affiliation: str = "") -> SpeakerInfo:
    return SpeakerInfo(
        name="x",
        affiliation=affiliation,
        role=role,
        start_seconds=0.0,
        start_time="00:00",
        duration_minutes=0,
    )


class TestFloorMeeting:
    def test_representative_questions(self) -> None:
        text = "本会議における代表質問"
        speakers = [_speaker("質疑者", "立憲民主党")]
        assert detect_session_kind(text, "本会議", speakers) == "representative_questions"

    def test_floor_speech_by_keyword(self) -> None:
        text = "解任決議案の趣旨説明"
        assert detect_session_kind(text, "本会議", []) == "floor_speech"

    def test_floor_speech_default(self) -> None:
        assert detect_session_kind("無関係なテキスト", "本会議", []) == "floor_speech"


class TestExpertHearing:
    def test_public_hearing_committee(self) -> None:
        assert detect_session_kind("", "予算公聴会", []) == "expert_hearing"

    def test_all_speakers_are_expert(self) -> None:
        speakers = [_speaker("参考人"), _speaker("参考人")]
        assert detect_session_kind("", "厚生労働委員会", speakers) == "expert_hearing"


class TestProcedural:
    def test_procedural_keyword(self) -> None:
        assert detect_session_kind("理事会", "議院運営委員会", []) == "procedural"


class TestRegularQA:
    def test_regular_committee(self) -> None:
        speakers = [_speaker("質疑者", "立憲民主党"), _speaker("答弁者", "経済産業大臣")]
        assert detect_session_kind("質疑応答", "経済産業委員会", speakers) == "regular_qa"
