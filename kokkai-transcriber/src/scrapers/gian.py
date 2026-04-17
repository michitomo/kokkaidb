"""衆議院・参議院の議案一覧スクレイパー。

衆法・参法を主なターゲットとし、閣法も取れる（タイトルのみ）。
提出理由はこのソースでは基本的に取れない（経過ページを個別fetchすれば取れる可能性があるが、
ラウンドトリップが増えるため今は省略）。

エンコーディングの注意:
    - 衆議院議案情報 (itdb_gian.nsf) は **Shift_JIS (CP932)** で返される。
      これは shugiintv.go.jp の EUC-JP とは異なるサブドメインの独自仕様。
      HTML の `<meta charset>` と Content-Type ヘッダが共に Shift_JIS を示す。
    - 参議院 (sangiin.go.jp/japanese/...) は UTF-8。

ページ構造:
    衆議院 (https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/kaiji{N}.htm):
        - `<table>` ごとに `<caption>` があり "衆法の一覧" / "参法の一覧" / "閣法の一覧" 等で
          区別されている（セクション順は 衆法 → 参法 → 閣法）。
        - 列: 提出回次, 番号, 議案件名, 審議状況, 経過情報, 本文情報
        - 経過ページへのリンクは相対URL `./keika/XXXXXXX.htm`。

    参議院 (https://www.sangiin.go.jp/japanese/joho1/kousei/gian/{N}/gian.htm):
        - `<h2 class="title_text">` で "法律案（内閣提出）一覧" / "法律案（衆法）一覧" /
          "法律案（参法）一覧" 等を区別（順: 閣法 → 衆法 → 参法）。
        - 直後の `<table class="list_c">` にデータ行。
        - 列: 提出回次, 提出番号, 件名, 議案要旨(PDF), 提出法律案(PDF)
        - 詳細ページ（"経過"相当）は相対URL `./meisai/mXXXXXXX.htm`。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.scrapers.bill_models import BillDetail, BillType

if TYPE_CHECKING:
    from bs4 import Tag

logger = logging.getLogger(__name__)

SHUGIIN_URL_TEMPLATE = (
    "https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/kaiji{session_id}.htm"
)
SANGIIN_URL_TEMPLATE = (
    "https://www.sangiin.go.jp/japanese/joho1/kousei/gian/{session_id}/gian.htm"
)

_USER_AGENT = "kokkaidb/0.1 (https://github.com/michitomo/kokkaidb)"

# 衆議院 <caption> テキスト → BillType のマッピング
_SHUGIIN_CAPTION_TYPE: dict[str, BillType] = {
    "閣法の一覧": "kakuhou",
    "衆法の一覧": "shuhou",
    "参法の一覧": "sanhou",
}

# 参議院 <h2> テキスト → BillType のマッピング
_SANGIIN_HEADING_TYPE: dict[str, BillType] = {
    "法律案（内閣提出）一覧": "kakuhou",
    "法律案（衆法）一覧": "shuhou",
    "法律案（参法）一覧": "sanhou",
}


@dataclass(frozen=True)
class _ParsedRow:
    """テーブル1行から抜き出した中間表現。"""

    bill_number: str
    title: str
    status: str | None
    detail_href: str | None


class GianScraper:
    """衆議院・参議院の議案一覧スクレイパー。

    Attributes:
        request_delay: list_all_bills() で衆参ページを連続fetchする際のスリープ秒数。
    """

    def __init__(self, request_delay: float = 0.5) -> None:
        self.request_delay = request_delay

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def list_shugiin_bills(self, session_id: int) -> list[BillDetail]:
        """衆議院議案一覧ページから法案リストを返す。

        Args:
            session_id: 国会回次（例: 221）。

        Returns:
            法案 `BillDetail` のリスト。セッションが未開催（404）の場合は空リスト。
        """
        url = SHUGIIN_URL_TEMPLATE.format(session_id=session_id)
        logger.info("Fetching shugiin gian list: %s", url)

        response = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=30)
        if response.status_code == 404:
            logger.warning("Shugiin gian page not found (session=%d): %s", session_id, url)
            return []
        response.raise_for_status()

        # 衆議院議案情報 (itdb_gian.nsf) は Shift_JIS。shugiintv.go.jp の EUC-JP とは別系統。
        response.encoding = "cp932"

        soup = BeautifulSoup(response.text, "html.parser")
        return _parse_shugiin_page(soup, session_id, url)

    def list_sangiin_bills(self, session_id: int) -> list[BillDetail]:
        """参議院議案一覧ページから法案リストを返す。

        Args:
            session_id: 国会回次（例: 221）。

        Returns:
            法案 `BillDetail` のリスト。セッションが未開催（404）の場合は空リスト。
        """
        url = SANGIIN_URL_TEMPLATE.format(session_id=session_id)
        logger.info("Fetching sangiin gian list: %s", url)

        response = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=30)
        if response.status_code == 404:
            logger.warning("Sangiin gian page not found (session=%d): %s", session_id, url)
            return []
        response.raise_for_status()
        response.encoding = "utf-8"

        soup = BeautifulSoup(response.text, "html.parser")
        return _parse_sangiin_page(soup, session_id, url)

    def list_all_bills(self, session_id: int) -> list[BillDetail]:
        """衆参両院の議案一覧を統合し、重複排除したリストを返す。

        閣法は両院のページで同じ法案が出るため重複しうる。衆法は衆議院提出、
        参法は参議院提出なのでタイトル上は重複しない想定だが、念のため
        `(type, title)` キーで dedup する。衆議院側のレコード（審議状況が
        取れる）を優先。

        Args:
            session_id: 国会回次（例: 221）。

        Returns:
            dedup 済みの `BillDetail` リスト。
        """
        shugiin_bills = self.list_shugiin_bills(session_id)
        if self.request_delay > 0:
            time.sleep(self.request_delay)
        sangiin_bills = self.list_sangiin_bills(session_id)

        merged: dict[tuple[BillType, str], BillDetail] = {}
        # 衆議院を先に入れることで、衆議院側の情報を優先保持する
        for bill in shugiin_bills:
            merged[(bill.type, bill.title)] = bill
        for bill in sangiin_bills:
            key = (bill.type, bill.title)
            if key not in merged:
                merged[key] = bill
        return list(merged.values())


# ---------------------------------------------------------------------- #
# Shugiin parsing
# ---------------------------------------------------------------------- #


def _parse_shugiin_page(soup: BeautifulSoup, session_id: int, page_url: str) -> list[BillDetail]:
    """衆議院議案一覧ページ全体をパース。"""
    bills: list[BillDetail] = []

    for table in soup.find_all("table"):
        caption = table.find("caption")
        if not caption:
            continue
        caption_text = caption.get_text(strip=True)
        bill_type = _SHUGIIN_CAPTION_TYPE.get(caption_text)
        if bill_type is None:
            continue  # 予算・条約・承認等はスキップ

        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 3:
                continue  # ヘッダ行 (th) など
            try:
                parsed = _parse_shugiin_row(cells)
            except Exception as exc:  # noqa: BLE001 — 個別行の失敗で全体を落とさない
                logger.warning(
                    "Skipping malformed shugiin row (session=%d, type=%s): %s",
                    session_id,
                    bill_type,
                    exc,
                )
                continue
            if parsed is None:
                continue

            source_url = (
                _absolutize(parsed.detail_href, page_url)
                if parsed.detail_href
                else page_url
            )
            bill_id = f"shugiin-{session_id}-{bill_type}-{parsed.bill_number}"
            bills.append(
                BillDetail(
                    id=bill_id,
                    type=bill_type,
                    title=parsed.title,
                    diet_session=session_id,
                    bill_number=parsed.bill_number,
                    status=parsed.status,
                    source_url=source_url,
                )
            )

    return bills


def _parse_shugiin_row(cells: list[Tag]) -> _ParsedRow | None:
    """衆議院議案テーブルの1行 (<td>のリスト) をパース。

    期待する列構造 (6列):
        [0] 提出回次 (例: "221")
        [1] 番号 (例: "1")
        [2] 議案件名
        [3] 審議状況 (例: "衆議院で審議中", "成立")
        [4] 経過情報 (<a href="./keika/XXX.htm">経過</a>)
        [5] 本文情報 (<a href="./honbun/XXX.htm">本文</a>)
    """
    if len(cells) < 4:
        return None
    bill_number = cells[1].get_text(strip=True)
    title = cells[2].get_text(strip=True)
    status = cells[3].get_text(strip=True) or None

    if not bill_number or not title:
        return None

    detail_href: str | None = None
    if len(cells) >= 5:
        keika_anchor = cells[4].find("a", href=True)
        if keika_anchor is not None:
            detail_href = str(keika_anchor["href"])

    return _ParsedRow(
        bill_number=bill_number,
        title=title,
        status=status,
        detail_href=detail_href,
    )


# ---------------------------------------------------------------------- #
# Sangiin parsing
# ---------------------------------------------------------------------- #


def _parse_sangiin_page(soup: BeautifulSoup, session_id: int, page_url: str) -> list[BillDetail]:
    """参議院議案一覧ページ全体をパース。"""
    bills: list[BillDetail] = []

    for heading in soup.find_all("h2"):
        heading_text = heading.get_text(strip=True)
        bill_type = _SANGIIN_HEADING_TYPE.get(heading_text)
        if bill_type is None:
            continue  # 予算・条約・承認等はスキップ

        table = _find_next_table(heading)
        if table is None:
            logger.warning(
                "No table found after heading '%s' for sangiin session=%d",
                heading_text,
                session_id,
            )
            continue

        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 3:
                continue
            try:
                parsed = _parse_sangiin_row(cells)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skipping malformed sangiin row (session=%d, type=%s): %s",
                    session_id,
                    bill_type,
                    exc,
                )
                continue
            if parsed is None:
                continue

            source_url = (
                _absolutize(parsed.detail_href, page_url)
                if parsed.detail_href
                else page_url
            )
            bill_id = f"sangiin-{session_id}-{bill_type}-{parsed.bill_number}"
            bills.append(
                BillDetail(
                    id=bill_id,
                    type=bill_type,
                    title=parsed.title,
                    diet_session=session_id,
                    bill_number=parsed.bill_number,
                    status=parsed.status,
                    source_url=source_url,
                )
            )

    return bills


def _parse_sangiin_row(cells: list[Tag]) -> _ParsedRow | None:
    """参議院議案テーブルの1行 (<td>のリスト) をパース。

    期待する列構造:
        [0] 提出回次 (例: "221")
        [1] 提出番号 (例: "1")
        [2] 件名 (<a href="./meisai/mXXX.htm">...</a>)
        [3] 議案要旨PDF (リンクがあれば)
        [4] 提出法律案PDF (リンクがあれば)

    参議院ページには審議状況の列がないため status は None を返す。
    """
    if len(cells) < 3:
        return None
    bill_number = cells[1].get_text(strip=True)
    title_cell = cells[2]
    title = title_cell.get_text(strip=True)
    if not bill_number or not title:
        return None

    detail_href: str | None = None
    title_anchor = title_cell.find("a", href=True)
    if title_anchor is not None:
        detail_href = str(title_anchor["href"])

    return _ParsedRow(
        bill_number=bill_number,
        title=title,
        status=None,
        detail_href=detail_href,
    )


def _find_next_table(heading: Tag) -> Tag | None:
    """指定した見出しタグの直後に現れる `<table>` を返す。"""
    for sibling in heading.find_all_next():
        if sibling.name == "table":
            return sibling
        if sibling.name == "h2":
            # 次の見出しに到達 → テーブルなし
            return None
    return None


# ---------------------------------------------------------------------- #
# Shared helpers
# ---------------------------------------------------------------------- #


def _absolutize(href: str, base_url: str) -> str:
    """相対URLを絶対URLに変換する。"""
    return urljoin(base_url, href)
