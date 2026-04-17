"""衆議院・参議院議案一覧スクレイパーのテスト。

結合テスト（`@pytest.mark.integration`）は実サイトに HTTP リクエストを送る。
ユニットテストとしての実行時には `-m "not integration"` でスキップ可能。
"""

from __future__ import annotations

import pytest

from src.scrapers.bill_models import BillDetail
from src.scrapers.gian import GianScraper


@pytest.mark.integration
def test_shugiin_221_has_shuhou() -> None:
    scraper = GianScraper()
    bills = scraper.list_shugiin_bills(221)
    shuhou = [b for b in bills if b.type == "shuhou"]

    # 第221回は2026-02-18開始の特別会で、本稿執筆時点では 6 件しか 衆法 が
    # 提出されていない（過去回次の session 217 では 84 件あった）。
    # セッション進行で増える可能性があるため下限を緩めに設定。
    assert len(shuhou) >= 4, f"expected >= 4 shuhou, got {len(shuhou)}"

    sample = shuhou[0]
    assert isinstance(sample, BillDetail)
    assert sample.diet_session == 221
    assert sample.title
    assert sample.source_url.startswith("https://www.shugiin.go.jp")
    assert sample.id.startswith("shugiin-221-shuhou-")
    # 衆議院ページには審議状況列があるので status が入っているはず
    assert sample.status, "expected status to be populated from shugiin page"


@pytest.mark.integration
def test_shugiin_221_has_all_three_types() -> None:
    """衆議院ページ 1 枚から 閣法/衆法/参法 の3種類がすべて取れることを確認。"""
    scraper = GianScraper()
    bills = scraper.list_shugiin_bills(221)
    types = {b.type for b in bills}
    assert types == {"kakuhou", "shuhou", "sanhou"}, f"got types: {types}"


@pytest.mark.integration
def test_sangiin_221_bills() -> None:
    scraper = GianScraper()
    bills = scraper.list_sangiin_bills(221)
    assert len(bills) > 0, "expected some bills from sangiin page"

    types = {b.type for b in bills}
    assert types & {"kakuhou", "shuhou", "sanhou"}, f"unexpected types: {types}"

    sample = bills[0]
    assert isinstance(sample, BillDetail)
    assert sample.diet_session == 221
    assert sample.title
    assert sample.source_url.startswith("https://www.sangiin.go.jp")
    assert sample.id.startswith("sangiin-221-")


@pytest.mark.integration
def test_list_all_bills_dedupes() -> None:
    """list_all_bills は衆参の重複を排除する。"""
    scraper = GianScraper(request_delay=0.5)
    combined = scraper.list_all_bills(221)
    # (type, title) で dedup されているはず
    keys = {(b.type, b.title) for b in combined}
    assert len(keys) == len(combined), "list_all_bills should return unique (type, title) pairs"
    # 3種類それぞれが1件以上含まれる
    assert {b.type for b in combined} == {"kakuhou", "shuhou", "sanhou"}


@pytest.mark.integration
def test_future_session_returns_empty() -> None:
    scraper = GianScraper()
    # session 999 は存在しない → 404 → 空リスト
    bills = scraper.list_shugiin_bills(999)
    assert bills == []


@pytest.mark.integration
def test_future_sangiin_session_returns_empty() -> None:
    scraper = GianScraper()
    bills = scraper.list_sangiin_bills(999)
    assert bills == []
