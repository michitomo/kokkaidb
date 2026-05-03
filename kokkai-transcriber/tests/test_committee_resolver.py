"""scrapers/_committee.resolve_committee の単体テスト"""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.models import SpeakerInfo
from src.scrapers._committee import (
    derive_committee_from_speakers,
    resolve_committee,
)


def _speaker(name: str, affiliation: str) -> SpeakerInfo:
    return SpeakerInfo(
        name=name,
        affiliation=affiliation,
        role="",
        start_seconds=0.0,
        start_time="00:00",
        duration_minutes=0,
    )


class TestStage1Title:
    def test_committee_in_title(self) -> None:
        html = "<html><head><title>厚生労働委員会 2026年4月9日</title></head></html>"
        soup = BeautifulSoup(html, "html.parser")
        assert resolve_committee(soup, []) == "厚生労働委員会"

    def test_floor_meeting_in_title(self) -> None:
        html = "<html><head><title>本会議 2026年4月9日</title></head></html>"
        soup = BeautifulSoup(html, "html.parser")
        assert resolve_committee(soup, []) == "本会議"


class TestStage1Body:
    def test_committee_in_h2(self) -> None:
        html = "<html><body><h2>法務委員会</h2></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        assert resolve_committee(soup, []) == "法務委員会"

    def test_special_category_examination_council(self) -> None:
        html = "<html><body><h2>憲法審査会</h2></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        assert resolve_committee(soup, []) == "憲法審査会"

    def test_nav_honkaigi_does_not_poison_committee_h2(self) -> None:
        """ナビゲーションの「本会議」span より h2 の委員会名を優先する（参議院TV再現）。"""
        html = (
            "<html><body>"
            "<div id='nav'><span>本会議</span><span>委員会</span></div>"
            "<div id='main'><h2>法務委員会</h2></div>"
            "</body></html>"
        )
        soup = BeautifulSoup(html, "html.parser")
        assert resolve_committee(soup, []) == "法務委員会"

    def test_nav_honkaigi_does_not_poison_committee_in_outer_div(self) -> None:
        """外側 div の get_text() に「本会議」が含まれても h2 の委員会名を優先する。"""
        html = (
            "<html><body>"
            "<div id='wrapper'>"
            "<div id='nav'><ul><li><span>本会議</span></li></ul></div>"
            "<div id='content'><h2>財政金融委員会</h2></div>"
            "</div>"
            "</body></html>"
        )
        soup = BeautifulSoup(html, "html.parser")
        assert resolve_committee(soup, []) == "財政金融委員会"


class TestStage2SpeakerFallback:
    def test_chair_affiliation_recovers_committee(self) -> None:
        html = "<html><body><div>内閣委員長 山下貴司</div></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        speakers = [_speaker("山下貴司", "内閣委員長")]
        # body にも "内閣委員会" の文字列がないため fallback で復旧
        assert resolve_committee(soup, speakers) == "内閣委員会"

    def test_derive_committee_only(self) -> None:
        speakers = [
            _speaker("田中太郎", "自由民主党"),
            _speaker("鈴木花子", "総務委員長"),
        ]
        assert derive_committee_from_speakers(speakers) == "総務委員会"

    def test_derive_committee_no_chair(self) -> None:
        speakers = [_speaker("田中太郎", "自由民主党")]
        assert derive_committee_from_speakers(speakers) == ""


class TestStage3Unknown:
    def test_no_committee_no_chair(self) -> None:
        html = "<html><body><div>議事手続のみ</div></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        speakers = [_speaker("田中太郎", "自由民主党")]
        assert resolve_committee(soup, speakers) == "不明"
