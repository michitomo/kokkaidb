"""laws_builder のユニットテスト（CLBScraper / GianScraper をモック化）。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.laws_builder import build_laws_json
from src.scrapers.bill_models import BillDetail


def _kakuhou(
    detail_id: int,
    title: str,
    session: int = 221,
    bill_number: str = "1",
    submitter: str = "財務省",
    reason: str | None = "経済対策のため本法律案を提出する。",
) -> BillDetail:
    return BillDetail(
        id=f"clb-{detail_id}",
        type="kakuhou",
        title=title,
        reason=reason,
        diet_session=session,
        bill_number=bill_number,
        submitter=submitter,
        submitted_at="2026-02-20",
        cabinet_decision_at="2026-02-15",
        status="衆議院で審議中",
        source_url=f"https://www.clb.go.jp/recent-laws/diet_bill/detail/id={detail_id}",
    )


def _shuhou(
    bill_number: str,
    title: str,
    session: int = 221,
) -> BillDetail:
    return BillDetail(
        id=f"shugiin-{session}-shuhou-{bill_number}",
        type="shuhou",
        title=title,
        diet_session=session,
        bill_number=bill_number,
        status="衆議院で審議中",
        source_url=f"https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/kaiji{session}.htm",
    )


def _sanhou(
    bill_number: str,
    title: str,
    session: int = 221,
) -> BillDetail:
    return BillDetail(
        id=f"sangiin-{session}-sanhou-{bill_number}",
        type="sanhou",
        title=title,
        diet_session=session,
        bill_number=bill_number,
        source_url=f"https://www.sangiin.go.jp/japanese/joho1/kousei/gian/{session}/gian.htm",
    )


@pytest.fixture
def mocked_scrapers():
    """CLBScraper/GianScraper をパッチして MagicMock を返すヘルパ。"""
    with patch("src.laws_builder.CLBScraper") as mock_clb_cls, patch(
        "src.laws_builder.GianScraper"
    ) as mock_gian_cls:
        mock_clb = MagicMock()
        mock_gian = MagicMock()
        mock_clb_cls.return_value = mock_clb
        mock_gian_cls.return_value = mock_gian
        yield mock_clb, mock_gian


def test_dedup_prefers_clb_over_gian(mocked_scrapers, tmp_path: Path) -> None:
    """同じ閣法が CLB と Gian 両方から返ってきた場合、CLB（提出理由あり）を残す。"""
    mock_clb, mock_gian = mocked_scrapers

    clb_bill = _kakuhou(
        detail_id=5149,
        title="財政運営に必要な財源の確保を図るための公債の発行の特例に関する法律案",
        reason="最近における国の財政収支が著しく不均衡な状況にかんがみ、特別な公債の発行を認める必要があるため。",
    )
    # Gian 側は CLB と「タイトルの空白の入り方だけ違う」同じ閣法を返してくる
    gian_same_kakuhou = BillDetail(
        id="shugiin-221-kakuhou-1",
        type="kakuhou",
        # 全角スペースを挟んだ、微妙に違う表記
        title="財政運営に必要な財源の確保を図るための公債の発行の特例に関する　法律案",
        diet_session=221,
        bill_number="1",
        status="衆議院で審議中",
        source_url="https://www.shugiin.go.jp/...",
    )
    gian_shuhou = _shuhou("1", "政治資金規正法の一部を改正する法律案")
    gian_sanhou = _sanhou("5", "地方自治法の一部を改正する法律案")

    mock_clb.scrape_session.return_value = [clb_bill]
    mock_gian.list_all_bills.return_value = [
        gian_same_kakuhou,
        gian_shuhou,
        gian_sanhou,
    ]

    build_laws_json(sessions=[221], output_dir=tmp_path)

    laws_json = json.loads((tmp_path / "laws.json").read_text(encoding="utf-8"))
    assert laws_json["count"] == 3
    assert laws_json["sessions_covered"] == [221]

    titles_by_type: dict[str, list[str]] = {}
    for bill in laws_json["bills"]:
        titles_by_type.setdefault(bill["type"], []).append(bill["title"])

    # 閣法は CLB 側（提出理由付き）が1件残る
    assert len(titles_by_type["kakuhou"]) == 1
    kakuhou_entry = next(b for b in laws_json["bills"] if b["type"] == "kakuhou")
    assert kakuhou_entry["id"] == "clb-5149"
    assert kakuhou_entry["reason"] is not None
    assert "財政収支" in kakuhou_entry["reason"]

    # 衆法・参法は Gian からそのまま1件ずつ
    assert titles_by_type["shuhou"] == ["政治資金規正法の一部を改正する法律案"]
    assert titles_by_type["sanhou"] == ["地方自治法の一部を改正する法律案"]


def test_laws_compact_txt_format(mocked_scrapers, tmp_path: Path) -> None:
    """laws_compact.txt の1行フォーマットが仕様どおり。"""
    mock_clb, mock_gian = mocked_scrapers

    mock_clb.scrape_session.return_value = [
        _kakuhou(
            detail_id=5149,
            title="AAA法律案",
            bill_number="1",
            submitter="財務省",
            reason="理由本文。",
        )
    ]
    mock_gian.list_all_bills.return_value = [
        _shuhou("1", "BBB法律案"),
        # submitter も reason も無い参法
        BillDetail(
            id="sangiin-221-sanhou-2",
            type="sanhou",
            title="CCC法律案",
            diet_session=221,
            bill_number="2",
            source_url="https://www.sangiin.go.jp/...",
        ),
    ]

    build_laws_json(sessions=[221], output_dir=tmp_path)

    compact_text = (tmp_path / "laws_compact.txt").read_text(encoding="utf-8")
    lines = [line for line in compact_text.splitlines() if line.strip()]
    assert len(lines) == 3

    # ソート: session desc → type (kakuhou→shuhou→sanhou) → bill_number asc
    # session はすべて 221 なので type 順になる
    assert lines[0].startswith("law_001: [閣法] AAA法律案")
    assert "財務省" in lines[0]
    assert "提出理由: 理由本文。" in lines[0]

    assert lines[1].startswith("law_002: [衆法] BBB法律案")
    # _shuhou は submitter を未設定にしているので含まれない
    assert "| 提出理由:" not in lines[1]

    assert lines[2].startswith("law_003: [参法] CCC法律案")
    # submitter も reason もないので、タイトルのみ
    assert lines[2] == "law_003: [参法] CCC法律案"


def test_reason_truncation(mocked_scrapers, tmp_path: Path) -> None:
    """200文字超の提出理由は切り詰められる。"""
    mock_clb, mock_gian = mocked_scrapers

    long_reason = "あ" * 300
    mock_clb.scrape_session.return_value = [
        _kakuhou(detail_id=1, title="長い理由の法律案", reason=long_reason)
    ]
    mock_gian.list_all_bills.return_value = []

    build_laws_json(sessions=[221], output_dir=tmp_path)

    compact_text = (tmp_path / "laws_compact.txt").read_text(encoding="utf-8")
    line = compact_text.splitlines()[0]
    assert "..." in line
    # 200文字 + "..." のはず
    reason_part = line.split("提出理由: ", 1)[1]
    assert reason_part.endswith("...")
    assert len(reason_part) == 203  # 200 + "..."


def test_laws_json_structure(mocked_scrapers, tmp_path: Path) -> None:
    """laws.json のトップレベル構造を検証する。"""
    mock_clb, mock_gian = mocked_scrapers

    mock_clb.scrape_session.return_value = [_kakuhou(detail_id=1, title="法案A")]
    mock_gian.list_all_bills.return_value = [_shuhou("1", "法案B")]

    build_laws_json(sessions=[220, 221], output_dir=tmp_path)

    data = json.loads((tmp_path / "laws.json").read_text(encoding="utf-8"))
    assert set(data.keys()) == {"generated_at", "sessions_covered", "count", "bills"}
    assert data["sessions_covered"] == [220, 221]
    assert isinstance(data["bills"], list)
    assert data["count"] == len(data["bills"])

    for bill in data["bills"]:
        # BillDetail が必須とする最小限のキー
        assert "id" in bill
        assert "type" in bill
        assert "title" in bill
        assert "diet_session" in bill
        assert "source_url" in bill


def test_sort_order(mocked_scrapers, tmp_path: Path) -> None:
    """session desc → type (kakuhou→shuhou→sanhou) → bill_number asc。"""
    mock_clb, mock_gian = mocked_scrapers

    # CLB を session ごとに違う返値にする
    def clb_side_effect(session: int) -> list[BillDetail]:
        if session == 221:
            return [
                _kakuhou(detail_id=10, title="221閣法1", session=221, bill_number="1"),
                _kakuhou(detail_id=11, title="221閣法2", session=221, bill_number="2"),
            ]
        if session == 220:
            return [_kakuhou(detail_id=20, title="220閣法1", session=220, bill_number="1")]
        return []

    def gian_side_effect(session: int) -> list[BillDetail]:
        if session == 221:
            return [_shuhou("3", "221衆法3", session=221)]
        return []

    mock_clb.scrape_session.side_effect = clb_side_effect
    mock_gian.list_all_bills.side_effect = gian_side_effect

    build_laws_json(sessions=[220, 221], output_dir=tmp_path)

    data = json.loads((tmp_path / "laws.json").read_text(encoding="utf-8"))
    order = [(b["diet_session"], b["type"], b["bill_number"]) for b in data["bills"]]
    # 221 kakuhou 1, 221 kakuhou 2, 221 shuhou 3, 220 kakuhou 1
    assert order == [
        (221, "kakuhou", "1"),
        (221, "kakuhou", "2"),
        (221, "shuhou", "3"),
        (220, "kakuhou", "1"),
    ]
