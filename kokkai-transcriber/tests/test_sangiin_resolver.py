"""sangiin_resolver の単体テスト"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audio.sangiin_resolver import _resolve_via_api, resolve_stream_url

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestResolveStreamUrl:
    def test_empty_hash_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            resolve_stream_url("")

    def test_successful_resolution(self) -> None:
        mock_response = MagicMock()
        mock_response.text = '''
        var config = {
            "url": "https://vod.mediasp.jp/sangiin/abc123/playlist.m3u8"
        };
        '''
        mock_response.raise_for_status = MagicMock()

        with patch("src.audio.sangiin_resolver.requests.get", return_value=mock_response):
            url = resolve_stream_url("abc123")

        assert url == "https://vod.mediasp.jp/sangiin/abc123/playlist.m3u8"
        assert ".m3u8" in url

    def test_mp4_fallback(self) -> None:
        mock_response = MagicMock()
        mock_response.text = '''
        var config = {
            "source": "https://vod.mediasp.jp/sangiin/abc123/video.mp4"
        };
        '''
        mock_response.raise_for_status = MagicMock()

        with patch("src.audio.sangiin_resolver.requests.get", return_value=mock_response):
            url = resolve_stream_url("abc123")

        assert url == "https://vod.mediasp.jp/sangiin/abc123/video.mp4"
        assert ".mp4" in url

    def test_no_url_found_raises(self) -> None:
        mock_response = MagicMock()
        mock_response.text = "<html><body>No video here</body></html>"
        mock_response.raise_for_status = MagicMock()

        with patch("src.audio.sangiin_resolver.requests.get", return_value=mock_response):
            with pytest.raises(ValueError, match="Could not resolve"):
                resolve_stream_url("nonexistent_hash")

    def test_network_error_raises(self) -> None:
        import requests

        with patch(
            "src.audio.sangiin_resolver.requests.get",
            side_effect=requests.ConnectionError("Network error"),
        ):
            with pytest.raises(ValueError, match="Could not resolve"):
                resolve_stream_url("abc123")


class TestResolveViaApi:
    def test_m3u8_pattern(self) -> None:
        mock_response = MagicMock()
        mock_response.text = 'var src = "https://vod.mediasp.jp/test/playlist.m3u8";'
        mock_response.raise_for_status = MagicMock()

        with patch("src.audio.sangiin_resolver.requests.get", return_value=mock_response):
            url = _resolve_via_api("testhash")

        assert url == "https://vod.mediasp.jp/test/playlist.m3u8"

    def test_vod_url_pattern(self) -> None:
        mock_response = MagicMock()
        mock_response.text = 'var stream = "https://vod.mediasp.jp/stream/12345";'
        mock_response.raise_for_status = MagicMock()

        with patch("src.audio.sangiin_resolver.requests.get", return_value=mock_response):
            url = _resolve_via_api("testhash")

        assert url == "https://vod.mediasp.jp/stream/12345"

    def test_returns_empty_on_no_match(self) -> None:
        mock_response = MagicMock()
        mock_response.text = "<html>No stream URLs</html>"
        mock_response.raise_for_status = MagicMock()

        with patch("src.audio.sangiin_resolver.requests.get", return_value=mock_response):
            url = _resolve_via_api("testhash")

        assert url == ""

    def test_fixture_file_parsing(self) -> None:
        """mediasp_player.js フィクスチャのパース。"""
        fixture_text = (FIXTURES_DIR / "mediasp_player.js").read_text(encoding="utf-8")

        mock_response = MagicMock()
        mock_response.text = fixture_text
        mock_response.raise_for_status = MagicMock()

        with patch("src.audio.sangiin_resolver.requests.get", return_value=mock_response):
            url = _resolve_via_api("abc123def456")

        assert "playlist.m3u8" in url
        assert url.startswith("https://")


@pytest.mark.integration
class TestResolverIntegration:
    def test_real_resolution(self) -> None:
        """実際の mediasp.jp へのリクエストをテストする（結合テスト）。

        注意: 実際のhashが必要なため、有効なhashがないとスキップされる。
        """
        pytest.skip("Requires a valid mediasp.jp hash for testing")
