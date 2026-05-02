"""衆議院スクレイパーの単体テスト"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models import SessionDetail
from src.scrapers.shugiin import (
    ShugiinScraper,
    _extract_hls_url,
    _parse_speaker_text,
    get_session_detail,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture_html() -> str:
    """EUC-JP エンコードされたフィクスチャHTMLを読み込んでUTF-8文字列として返す。"""
    html_bytes = (FIXTURES_DIR / "shugiin_56149.html").read_bytes()
    # フィクスチャはASCII/UTF-8 互換なのでそのままデコード
    try:
        return html_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return html_bytes.decode("euc-jp")


def _load_calendar_fixture_html() -> str:
    """カレンダーページのフィクスチャHTMLを読み込む。"""
    html_bytes = (FIXTURES_DIR / "shugiin_calendar_20260409.html").read_bytes()
    try:
        return html_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return html_bytes.decode("euc-jp")


class TestParseSpeakerText:
    def test_name_with_affiliation(self) -> None:
        name, affiliation = _parse_speaker_text("古川あおい(チームみらい)")
        assert name == "古川あおい"
        assert affiliation == "チームみらい"

    def test_name_with_role_title(self) -> None:
        name, affiliation = _parse_speaker_text("伊藤孝恵(法務委員長)")
        assert name == "伊藤孝恵"
        assert affiliation == "法務委員長"

    def test_name_only(self) -> None:
        name, affiliation = _parse_speaker_text("古川あおい")
        assert name == "古川あおい"
        assert affiliation == ""

    def test_name_with_party_containing_parentheses_like_chars(self) -> None:
        name, affiliation = _parse_speaker_text("山谷えり子(自由民主党・無所属の会)")
        assert name == "山谷えり子"
        assert affiliation == "自由民主党・無所属の会"

    def test_whitespace_stripped(self) -> None:
        name, affiliation = _parse_speaker_text("  古川あおい (チームみらい) ")
        assert name == "古川あおい"
        assert affiliation == "チームみらい"


class TestExtractHlsUrl:
    def test_relative_path(self) -> None:
        from bs4 import BeautifulSoup
        html = '<input type="hidden" id="vtag_src_base_vod" value="2026/2026-0409-1300-00/playlist.m3u8">'
        soup = BeautifulSoup(html, "html.parser")
        url = _extract_hls_url(soup)
        assert url == "https://hlsvod.shugiintv.go.jp/vod/_definst_/amlst:2026/2026-0409-1300-00/playlist.m3u8"

    def test_http_normalized_to_https(self) -> None:
        from bs4 import BeautifulSoup
        http_url = "http://hlsvod.shugiintv.go.jp/vod/_definst_/amlst:2026/2026-0409-1300-00/playlist.m3u8"
        html = f'<input type="hidden" id="vtag_src_base_vod" value="{http_url}">'
        soup = BeautifulSoup(html, "html.parser")
        url = _extract_hls_url(soup)
        assert url == "https://hlsvod.shugiintv.go.jp/vod/_definst_/amlst:2026/2026-0409-1300-00/playlist.m3u8"

    def test_https_url_unchanged(self) -> None:
        from bs4 import BeautifulSoup
        https_url = "https://hlsvod.shugiintv.go.jp/vod/_definst_/amlst:2026/2026-0409-1300-00/playlist.m3u8"
        html = f'<input type="hidden" id="vtag_src_base_vod" value="{https_url}">'
        soup = BeautifulSoup(html, "html.parser")
        url = _extract_hls_url(soup)
        assert url == https_url

    def test_missing_tag_returns_empty(self) -> None:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup("<html></html>", "html.parser")
        url = _extract_hls_url(soup)
        assert url == ""


class TestGetSessionDetailWithFixture:
    def test_scrape_fixture_html(self) -> None:
        """保存済みフィクスチャHTMLでスクレイピングをテストする。"""
        html_content = _load_fixture_html()

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.raise_for_status = MagicMock()

        with patch("src.scrapers.shugiin.requests.get", return_value=mock_response):
            result = get_session_detail("56149")

        assert isinstance(result, SessionDetail)
        assert result.session_id == "56149"
        assert result.chamber == "shugiin"

    def test_correct_number_of_speakers(self) -> None:
        """発言者が正しい数で抽出されること。"""
        html_content = _load_fixture_html()

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.raise_for_status = MagicMock()

        with patch("src.scrapers.shugiin.requests.get", return_value=mock_response):
            result = get_session_detail("56149")

        # フィクスチャに4名の発言者がいる
        assert len(result.speakers) == 4

    def test_speaker_order_preserved(self) -> None:
        """発言者リストが正しい順序で抽出されること。"""
        html_content = _load_fixture_html()

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.raise_for_status = MagicMock()

        with patch("src.scrapers.shugiin.requests.get", return_value=mock_response):
            result = get_session_detail("56149")

        speaker_names = [s.name for s in result.speakers]
        assert speaker_names[0] == "藤原徹"
        assert speaker_names[1] == "古川あおい"
        assert speaker_names[2] == "山田花子"
        assert speaker_names[3] == "伊藤孝恵"

    def test_hls_url_format(self) -> None:
        """HLS URLが正しいフォーマットであること。"""
        html_content = _load_fixture_html()

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.raise_for_status = MagicMock()

        with patch("src.scrapers.shugiin.requests.get", return_value=mock_response):
            result = get_session_detail("56149")

        assert result.hls_url.startswith("https://hlsvod.shugiintv.go.jp/")
        assert "playlist.m3u8" in result.hls_url

    def test_speaker_with_role_in_affiliation(self) -> None:
        """カッコ内に役職が含まれるケース（伊藤孝恵(法務委員長)）のパース。"""
        html_content = _load_fixture_html()

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.raise_for_status = MagicMock()

        with patch("src.scrapers.shugiin.requests.get", return_value=mock_response):
            result = get_session_detail("56149")

        ito = next((s for s in result.speakers if s.name == "伊藤孝恵"), None)
        assert ito is not None
        assert ito.affiliation == "法務委員長"

    def test_start_seconds_parsed(self) -> None:
        """開始秒数が正しく浮動小数点でパースされること。"""
        html_content = _load_fixture_html()

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.raise_for_status = MagicMock()

        with patch("src.scrapers.shugiin.requests.get", return_value=mock_response):
            result = get_session_detail("56149")

        furukawa = next((s for s in result.speakers if s.name == "古川あおい"), None)
        assert furukawa is not None
        assert furukawa.start_seconds == 7320.2

    def test_japanese_characters_decoded_correctly(self) -> None:
        """日本語文字列が正しくデコードされること。"""
        html_content = _load_fixture_html()

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.raise_for_status = MagicMock()

        with patch("src.scrapers.shugiin.requests.get", return_value=mock_response):
            result = get_session_detail("56149")

        # 日本語が化けていないこと
        assert any("古川" in s.name for s in result.speakers)
        assert any("チームみらい" in s.affiliation for s in result.speakers)

    def test_date_extracted_from_title(self) -> None:
        """タイトルから日付が正しく抽出されること。"""
        html_content = _load_fixture_html()

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.raise_for_status = MagicMock()

        with patch("src.scrapers.shugiin.requests.get", return_value=mock_response):
            result = get_session_detail("56149")

        assert result.date == "2026-04-09"

    def test_committee_extracted(self) -> None:
        """委員会名が抽出されること。"""
        html_content = _load_fixture_html()

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.raise_for_status = MagicMock()

        with patch("src.scrapers.shugiin.requests.get", return_value=mock_response):
            result = get_session_detail("56149")

        assert result.committee == "本会議"

    def test_session_kind_for_floor_meeting(self) -> None:
        """本会議の session_kind が floor_speech 系列に分類されること。"""
        html_content = _load_fixture_html()

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.raise_for_status = MagicMock()

        with patch("src.scrapers.shugiin.requests.get", return_value=mock_response):
            result = get_session_detail("56149")

        assert result.session_kind in {
            "floor_speech",
            "representative_questions",
        }

    def test_speakers_have_role_assigned(self) -> None:
        """全 speaker に role が派生（空文字でない）されていること。"""
        html_content = _load_fixture_html()

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.raise_for_status = MagicMock()

        with patch("src.scrapers.shugiin.requests.get", return_value=mock_response):
            result = get_session_detail("56149")

        for speaker in result.speakers:
            assert speaker.role != ""


class TestShugiinScraperClass:
    """ShugiinScraperクラスのテスト。"""

    def test_chamber_attribute(self) -> None:
        """chamberが"shugiin"であること。"""
        scraper = ShugiinScraper()
        assert scraper.chamber == "shugiin"

    def test_get_session_detail_returns_session_detail(self) -> None:
        """get_session_detail()がSessionDetailを返すこと。"""
        html_content = _load_fixture_html()

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.raise_for_status = MagicMock()

        with patch("src.scrapers.shugiin.requests.get", return_value=mock_response):
            scraper = ShugiinScraper()
            result = scraper.get_session_detail("56149")

        assert isinstance(result, SessionDetail)
        assert result.session_id == "56149"

    def test_detect_new_sessions(self) -> None:
        """detect_new_sessions()がdeli_idリストを返すこと。"""
        html_content = _load_calendar_fixture_html()

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.raise_for_status = MagicMock()

        with patch("src.scrapers.shugiin.requests.get", return_value=mock_response):
            scraper = ShugiinScraper()
            ids = scraper.detect_new_sessions("2026-04-09")

        assert "56149" in ids
        assert "56150" in ids
        assert all(id.isdigit() for id in ids)

    def test_detect_new_sessions_no_duplicates(self) -> None:
        """detect_new_sessions()が重複を除去すること。"""
        html_content = """
        <a href="/jp/index.php?ex=VL&deli_id=56149">本会議</a>
        <a href="/jp/index.php?ex=VL&deli_id=56149&time=100">はじめから再生</a>
        """

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.raise_for_status = MagicMock()

        with patch("src.scrapers.shugiin.requests.get", return_value=mock_response):
            scraper = ShugiinScraper()
            ids = scraper.detect_new_sessions("2026-04-09")

        assert ids.count("56149") == 1

    def test_get_audio_url_returns_hls_url(self) -> None:
        """get_audio_url()がHLS URLを返すこと。"""
        html_content = _load_fixture_html()

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.raise_for_status = MagicMock()

        with patch("src.scrapers.shugiin.requests.get", return_value=mock_response):
            scraper = ShugiinScraper()
            url = scraper.get_audio_url("56149")

        assert "hlsvod.shugiintv.go.jp" in url
        assert url.startswith("https://")


@pytest.mark.integration
class TestGetSessionDetailIntegration:
    def test_real_request(self) -> None:
        """実際の shugiintv.go.jp へのリクエストをテストする（結合テスト）。"""
        result = get_session_detail("56149")
        assert isinstance(result, SessionDetail)
        assert len(result.speakers) > 0
        assert result.hls_url

    def test_detect_new_sessions_real(self) -> None:
        """実際の shugiintv.go.jp カレンダーからセッションIDを取得する（結合テスト）。"""
        scraper = ShugiinScraper()
        ids = scraper.detect_new_sessions("2026-04-09")
        assert isinstance(ids, list)
        assert "56149" in ids
