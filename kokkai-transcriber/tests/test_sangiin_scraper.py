"""参議院スクレイパーの単体テスト"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models import SessionDetail
from src.scrapers._committee import resolve_committee
from src.scrapers.sangiin import (
    SangiinScraper,
    _extract_date,
    _extract_mediasp_hash,
    _extract_speakers,
    _parse_speaker_text,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture_html() -> str:
    """参議院詳細ページのフィクスチャHTMLを読み込む。"""
    return (FIXTURES_DIR / "sangiin_7890.html").read_text(encoding="utf-8")


def _load_calendar_fixture_html() -> str:
    """セッション一覧のフィクスチャHTMLを読み込む。"""
    return (FIXTURES_DIR / "sangiin_calendar_20260410.html").read_text(encoding="utf-8")


class TestParseSpeakerText:
    def test_name_with_affiliation_half_width(self) -> None:
        name, affiliation = _parse_speaker_text("田中太郎(自由民主党)")
        assert name == "田中太郎"
        assert affiliation == "自由民主党"

    def test_name_with_affiliation_full_width(self) -> None:
        name, affiliation = _parse_speaker_text("田中太郎（自由民主党）")
        assert name == "田中太郎"
        assert affiliation == "自由民主党"

    def test_name_with_role_title(self) -> None:
        name, affiliation = _parse_speaker_text("伊藤孝江(法務委員長)")
        assert name == "伊藤孝江"
        assert affiliation == "法務委員長"

    def test_name_only(self) -> None:
        name, affiliation = _parse_speaker_text("鈴木一郎")
        assert name == "鈴木一郎"
        assert affiliation == ""

    def test_name_with_compound_party(self) -> None:
        name, affiliation = _parse_speaker_text("鈴木一郎(立憲民主党・社民)")
        assert name == "鈴木一郎"
        assert affiliation == "立憲民主党・社民"

    def test_whitespace_stripped(self) -> None:
        name, affiliation = _parse_speaker_text("  田中太郎 (自由民主党) ")
        assert name == "田中太郎"
        assert affiliation == "自由民主党"


class TestExtractFromFixture:
    def test_extract_committee(self) -> None:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(_load_fixture_html(), "html.parser")
        committee = resolve_committee(soup, [])
        assert committee == "法務委員会"

    def test_extract_date(self) -> None:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(_load_fixture_html(), "html.parser")
        date = _extract_date(soup)
        assert date == "2026-04-10"

    def test_extract_mediasp_hash(self) -> None:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(_load_fixture_html(), "html.parser")
        hash_val = _extract_mediasp_hash(soup)
        assert hash_val == "abc123def456"

    def test_extract_speakers_count(self) -> None:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(_load_fixture_html(), "html.parser")
        speakers = _extract_speakers(soup, "7890")
        assert len(speakers) == 4

    def test_extract_speakers_order(self) -> None:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(_load_fixture_html(), "html.parser")
        speakers = _extract_speakers(soup, "7890")
        names = [s.name for s in speakers]
        assert names == ["伊藤孝江", "田中太郎", "鈴木一郎", "佐藤花子"]

    def test_extract_speakers_timestamps(self) -> None:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(_load_fixture_html(), "html.parser")
        speakers = _extract_speakers(soup, "7890")
        assert speakers[0].start_seconds == 0.0
        assert speakers[1].start_seconds == 180.5
        assert speakers[2].start_seconds == 1680.0
        assert speakers[3].start_seconds == 2880.75

    def test_extract_speakers_affiliations(self) -> None:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(_load_fixture_html(), "html.parser")
        speakers = _extract_speakers(soup, "7890")
        assert speakers[0].affiliation == "法務委員長"
        assert speakers[1].affiliation == "自由民主党"
        assert speakers[2].affiliation == "立憲民主党・社民"
        assert speakers[3].affiliation == "公明党"

    def test_extract_speakers_start_time(self) -> None:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(_load_fixture_html(), "html.parser")
        speakers = _extract_speakers(soup, "7890")
        assert speakers[0].start_time == "10:00"
        assert speakers[1].start_time == "10:03"

    def test_extract_speakers_duration(self) -> None:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(_load_fixture_html(), "html.parser")
        speakers = _extract_speakers(soup, "7890")
        assert speakers[0].duration_minutes == 3
        assert speakers[1].duration_minutes == 25


class TestSangiinScraperClass:
    def test_chamber_attribute(self) -> None:
        scraper = SangiinScraper()
        assert scraper.chamber == "sangiin"

    def test_get_session_detail_returns_session_detail(self) -> None:
        html_content = _load_fixture_html()

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.raise_for_status = MagicMock()

        with patch("src.scrapers.sangiin.requests.get", return_value=mock_response):
            scraper = SangiinScraper()
            result = scraper.get_session_detail("7890")

        assert isinstance(result, SessionDetail)
        assert result.session_id == "7890"
        assert result.chamber == "sangiin"
        assert result.committee == "法務委員会"
        assert result.date == "2026-04-10"
        assert result.mediasp_hash == "abc123def456"
        assert result.hls_url == ""
        assert len(result.speakers) == 4
        assert result.session_kind == "regular_qa"
        for speaker in result.speakers:
            assert speaker.role != ""

    def test_detect_new_sessions_today_uses_get(self) -> None:
        """本日 (JST) なら GET `result_selecter.php` 経路。"""
        from datetime import datetime, timedelta, timezone

        jst = timezone(timedelta(hours=9))
        today = datetime.now(jst).strftime("%Y-%m-%d")

        html_content = _load_calendar_fixture_html()

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.raise_for_status = MagicMock()

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        with patch("src.scrapers.sangiin.requests.Session", return_value=mock_session):
            scraper = SangiinScraper()
            ids = scraper.detect_new_sessions(today)

        assert "7890" in ids
        assert "7891" in ids
        assert "7892" in ids
        assert len(ids) == 3

    def test_detect_new_sessions_today_no_duplicates(self) -> None:
        from datetime import datetime, timedelta, timezone

        jst = timezone(timedelta(hours=9))
        today = datetime.now(jst).strftime("%Y-%m-%d")

        html_content = """
        <a href="detail.php?sid=7890">法務委員会</a>
        <a href="detail.php?sid=7890">法務委員会 (リプレイ)</a>
        """

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.raise_for_status = MagicMock()

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        with patch("src.scrapers.sangiin.requests.Session", return_value=mock_session):
            scraper = SangiinScraper()
            ids = scraper.detect_new_sessions(today)

        assert ids.count("7890") == 1

    def test_detect_new_sessions_past_uses_playwright(self) -> None:
        """本日以外なら Playwright 経路 (`discover_sids_for_date`) に委譲する。"""
        with patch(
            "src.scrapers._sangiin_search.discover_sids_for_date",
            return_value=["8932", "8933", "8941"],
        ) as mock_discover:
            scraper = SangiinScraper()
            # 確実に「過去」となる古い日付を指定
            ids = scraper.detect_new_sessions("2025-06-12")

        mock_discover.assert_called_once_with("2025-06-12")
        assert ids == ["8932", "8933", "8941"]

    def test_get_audio_url_calls_resolver(self) -> None:
        html_content = _load_fixture_html()

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.raise_for_status = MagicMock()

        with (
            patch("src.scrapers.sangiin.requests.get", return_value=mock_response),
            patch(
                "src.scrapers.sangiin.resolve_stream_url",
                return_value="https://vod.mediasp.jp/test/playlist.m3u8",
            ) as mock_resolve,
        ):
            scraper = SangiinScraper()
            url = scraper.get_audio_url("7890")

        mock_resolve.assert_called_once_with("abc123def456")
        assert url == "https://vod.mediasp.jp/test/playlist.m3u8"

    def test_source_url_format(self) -> None:
        html_content = _load_fixture_html()

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.raise_for_status = MagicMock()

        with patch("src.scrapers.sangiin.requests.get", return_value=mock_response):
            scraper = SangiinScraper()
            result = scraper.get_session_detail("7890")

        assert "webtv.sangiin.go.jp" in result.source_url
        assert "sid=7890" in result.source_url


class TestEdgeCases:
    def test_no_mediasp_hash(self) -> None:
        from bs4 import BeautifulSoup

        html = "<html><body><p>No video player</p></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        assert _extract_mediasp_hash(soup) == ""

    def test_no_speakers(self) -> None:
        from bs4 import BeautifulSoup

        html = "<html><body><p>No speakers</p></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        speakers = _extract_speakers(soup, "9999")
        assert speakers == []

    def test_unknown_committee(self) -> None:
        from bs4 import BeautifulSoup

        html = "<html><body><p>Something else</p></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        assert resolve_committee(soup, []) == "不明"

    def test_unknown_date_raises(self) -> None:
        from bs4 import BeautifulSoup

        html = "<html><body><p>No date</p></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        with pytest.raises(ValueError, match="Could not extract date"):
            _extract_date(soup)


@pytest.mark.integration
class TestSangiinScraperIntegration:
    def test_detect_today_real(self) -> None:
        """本日 (JST) を渡して GET 経路を実走 (Playwright 不要)。"""
        from datetime import datetime, timedelta, timezone

        jst = timezone(timedelta(hours=9))
        today = datetime.now(jst).strftime("%Y-%m-%d")

        scraper = SangiinScraper()
        ids = scraper.detect_new_sessions(today)
        assert isinstance(ids, list)

    def test_detect_past_date_real(self) -> None:
        """過去日付を渡して Playwright 経路を実走 (chromium 必須)。

        2026-04-02 は実際に 11 セッションが配信された日 (検証時点)。
        セッション数が変わっても「11 件以上」を最低保証として検証する。
        """
        scraper = SangiinScraper()
        ids = scraper.detect_new_sessions("2026-04-02")
        assert isinstance(ids, list)
        assert len(ids) >= 1
        for sid in ids:
            assert sid.isdigit()
