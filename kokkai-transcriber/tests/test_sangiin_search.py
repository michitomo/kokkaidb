"""`src/scrapers/_sangiin_search.py` の単体テスト

Playwright 自体は外部依存なのでネットワークを伴うテストは
`@pytest.mark.integration` で隔離し、デフォルトでは
`_parse_search_responses` のロジックのみを検証する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.scrapers._sangiin_search import _parse_search_responses, discover_sids_for_date

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_real_response() -> str:
    return (FIXTURES_DIR / "sangiin_search_2026-04-02.html").read_text(encoding="utf-8")


def _load_waf_rejected() -> str:
    return (FIXTURES_DIR / "sangiin_search_waf_rejected.html").read_text(encoding="utf-8")


class TestParseSearchResponses:
    def test_extracts_sids_from_real_response(self) -> None:
        html = _load_real_response()
        sids = _parse_search_responses([html], "2026-04-02")
        # 2026-04-02 は実際に 11 セッション (sid 8932..8942) の日。
        assert sids == [
            "8932", "8933", "8934", "8935", "8936",
            "8937", "8938", "8939", "8940", "8941", "8942",
        ]

    def test_dedups_across_multiple_responses(self) -> None:
        html = _load_real_response()
        sids = _parse_search_responses([html, html, html], "2026-04-02")
        assert sids.count("8941") == 1
        assert len(sids) == 11

    def test_raises_when_all_responses_rejected(self) -> None:
        rej = _load_waf_rejected()
        with pytest.raises(RuntimeError, match="WAF-rejected"):
            _parse_search_responses([rej, rej], "2026-04-02")

    def test_partial_rejection_recovers_sids(self) -> None:
        """一部応答だけ rejected で他応答に sid が含まれるケース。"""
        rej = _load_waf_rejected()
        html = _load_real_response()
        sids = _parse_search_responses([rej, html], "2026-04-02")
        assert "8941" in sids
        assert len(sids) == 11

    def test_raises_when_no_responses(self) -> None:
        with pytest.raises(RuntimeError, match="No keyword_search.php response"):
            _parse_search_responses([], "2026-04-02")

    def test_returns_empty_for_no_sessions_day(self) -> None:
        """空ボディ (sid なし、WAF rejection でもない) → 空リスト。"""
        html = (
            "<div><p class='hit-num'>ヒット件数：<span id='total_no'>0</span>件</p>"
            "<p>該当する検索結果はありません</p></div>"
        )
        sids = _parse_search_responses([html], "2026-05-01")
        assert sids == []


class TestDiscoverSidsForDate:
    def test_raises_when_playwright_not_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """playwright が import 不可なら明示的に RuntimeError を投げる。"""
        import builtins

        original_import = builtins.__import__

        def _fail_on_playwright(name: str, *args: object, **kwargs: object) -> object:
            if name in ("playwright", "playwright.sync_api", "playwright_stealth"):
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fail_on_playwright)

        with pytest.raises(RuntimeError, match="playwright .* required"):
            discover_sids_for_date("2026-04-02")

    def test_invalid_date_format_raises(self) -> None:
        """日付フォーマットが壊れていれば即時 ValueError。"""
        with pytest.raises(ValueError):
            discover_sids_for_date("not-a-date")


@pytest.mark.integration
class TestDiscoverSidsForDateIntegration:
    """実 webtv.sangiin.go.jp に対する E2E (Playwright + chromium 必須)。"""

    def test_real_past_date(self) -> None:
        sids = discover_sids_for_date("2026-04-02")
        # 2026-04-02 の sid 範囲 (検証時点)
        assert sids
        for sid in sids:
            assert sid.isdigit()
