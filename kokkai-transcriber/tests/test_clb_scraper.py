"""内閣法制局（CLB）スクレイパーのテスト。

結合テスト（`@pytest.mark.integration`）は実サイトに HTTP リクエストを送る。
ユニットテストとしての実行時には `-m "not integration"` でスキップ可能。
"""

from __future__ import annotations

import pytest

from src.scrapers.clb import BillDetail, CLBScraper


@pytest.mark.integration
def test_fetch_detail_5149() -> None:
    scraper = CLBScraper()
    bill = scraper.get_bill_detail(5149)
    assert isinstance(bill, BillDetail)
    assert bill.id == "clb-5149"
    assert bill.type == "kakuhou"
    assert bill.diet_session == 221
    assert "財政" in bill.title or "公債" in bill.title
    assert bill.reason is not None and len(bill.reason) > 20
    assert bill.submitter == "財務省"
    assert bill.source_url == "https://www.clb.go.jp/recent-laws/diet_bill/detail/id=5149"


@pytest.mark.integration
def test_list_session_ids_contains_221() -> None:
    scraper = CLBScraper()
    mapping = scraper.list_session_ids()
    assert 221 in mapping
    # 221 list page should be id=5144 per prior research
    assert mapping[221] == 5144


@pytest.mark.integration
def test_list_detail_ids_for_221() -> None:
    scraper = CLBScraper()
    ids = scraper.list_detail_ids(5144)
    # 第221回 had 60 kakuhou bills
    assert len(ids) >= 50
    assert 5149 in ids
