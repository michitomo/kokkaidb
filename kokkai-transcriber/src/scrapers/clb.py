"""内閣法制局 recent-laws スクレイパー（閣法のみ）

LLMプロンプト用に法案タイトル+提出理由を取得する。
衆法・参法はこのサイトには載っていない（別途 gian.py で取得）。

サイト構造:
    - ランディング: https://www.clb.go.jp/recent-laws/
        各国会回次へのリンク（/recent-laws/diet_bill/id={list_id}）を列挙。
    - 回次リスト: https://www.clb.go.jp/recent-laws/diet_bill/id={list_id}
        その国会の閣法詳細ページ（/detail/id={detail_id}）を列挙。
    - 法案詳細: https://www.clb.go.jp/recent-laws/diet_bill/detail/id={detail_id}
        `<dl class="c-table--column2">` に項目が dt/dd で並ぶ。

IDは（条約ページ等と共通の）グローバル連番。直接推測せず必ず
ランディング → リスト → 詳細 の順で辿る。
"""

from __future__ import annotations

import logging
import re
import time

import requests
from bs4 import BeautifulSoup, Tag

from src.scrapers.bill_models import BillDetail

__all__ = ["BillDetail", "CLBScraper"]

logger = logging.getLogger(__name__)

BASE_URL = "https://www.clb.go.jp"
LANDING_URL = f"{BASE_URL}/recent-laws/"
LIST_URL_TEMPLATE = f"{BASE_URL}/recent-laws/diet_bill/id={{list_id}}"
DETAIL_URL_TEMPLATE = f"{BASE_URL}/recent-laws/diet_bill/detail/id={{detail_id}}"

_USER_AGENT = "kokkaidb/0.1 (https://github.com/michitomo/kokkaidb)"


class CLBScraper:
    """内閣法制局 recent-laws スクレイパー。

    Attributes:
        request_delay: 連続リクエスト間のスリープ秒数（サイト負荷軽減）
    """

    def __init__(self, request_delay: float = 0.5) -> None:
        self.request_delay = request_delay
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})

    # ------------------------------------------------------------------ public

    def list_session_ids(self) -> dict[int, int]:
        """ランディングページから「国会回次 → リストページID」のマッピングを返す。

        Returns:
            `{diet_session: list_page_id}` の dict（例: `{221: 5144, 220: 5134, ...}`）
        """
        logger.info("Fetching CLB landing page: %s", LANDING_URL)
        response = self._session.get(LANDING_URL, timeout=30)
        response.raise_for_status()
        response.encoding = "utf-8"

        soup = BeautifulSoup(response.text, "html.parser")
        mapping: dict[int, int] = {}

        # /recent-laws/diet_bill/id=XXXX 形式のリンクを全探索し、
        # アンカーテキスト中の "第NNN回" から回次を取得する。
        list_link_pattern = re.compile(r"/recent-laws/diet_bill/id=(\d+)")
        session_text_pattern = re.compile(r"第(\d+)回")
        for anchor in soup.find_all("a", href=list_link_pattern):
            if not isinstance(anchor, Tag):
                continue
            href = str(anchor.get("href", ""))
            id_match = list_link_pattern.search(href)
            text_match = session_text_pattern.search(anchor.get_text(strip=True))
            if not id_match or not text_match:
                continue
            list_id = int(id_match.group(1))
            diet_session = int(text_match.group(1))
            # 同じ回次が複数出現した場合は最初のもの（＝最新/大きいlist_id）を優先
            mapping.setdefault(diet_session, list_id)

        logger.info("Found %d session(s) on CLB landing page", len(mapping))
        return mapping

    def list_detail_ids(self, list_page_id: int) -> list[int]:
        """リストページからその国会の閣法detail IDをソース順に返す。

        Args:
            list_page_id: `list_session_ids()` で得たリストページID

        Returns:
            detail IDの整数リスト（出現順・重複除去）
        """
        url = LIST_URL_TEMPLATE.format(list_id=list_page_id)
        logger.info("Fetching CLB session list: %s", url)
        response = self._session.get(url, timeout=30)
        response.raise_for_status()
        response.encoding = "utf-8"

        soup = BeautifulSoup(response.text, "html.parser")

        detail_link_pattern = re.compile(r"/recent-laws/diet_bill/detail/id=(\d+)")
        seen: set[int] = set()
        ids: list[int] = []
        for anchor in soup.find_all("a", href=detail_link_pattern):
            if not isinstance(anchor, Tag):
                continue
            match = detail_link_pattern.search(str(anchor.get("href", "")))
            if not match:
                continue
            detail_id = int(match.group(1))
            if detail_id in seen:
                continue
            seen.add(detail_id)
            ids.append(detail_id)

        logger.info("Found %d detail id(s) on list page id=%d", len(ids), list_page_id)
        return ids

    def get_bill_detail(self, detail_id: int) -> BillDetail:
        """詳細ページをスクレイプして `BillDetail` を返す。

        Args:
            detail_id: 詳細ページID

        Returns:
            BillDetail

        Raises:
            requests.HTTPError: HTTPエラー時
            ValueError: タイトル・国会回次といった必須項目が見つからない場合
        """
        url = DETAIL_URL_TEMPLATE.format(detail_id=detail_id)
        response = self._session.get(url, timeout=30)
        response.raise_for_status()
        response.encoding = "utf-8"

        soup = BeautifulSoup(response.text, "html.parser")
        dl = soup.find("dl", class_="c-table--column2")
        if not isinstance(dl, Tag):
            raise ValueError(f"dl.c-table--column2 not found on detail id={detail_id}")

        fields = _parse_dl_pairs(dl)

        title = _get_text(fields.get("法律案名"))
        if not title:
            raise ValueError(f"Missing required field 法律案名 on detail id={detail_id}")

        diet_session_text = _get_text(fields.get("提出国会"))
        diet_session_match = re.search(r"第(\d+)回", diet_session_text or "")
        if not diet_session_match:
            raise ValueError(
                f"Could not parse 提出国会 ('{diet_session_text}') on detail id={detail_id}"
            )
        diet_session = int(diet_session_match.group(1))

        bill_number = _get_text(fields.get("閣法番号")) or ""
        if not bill_number:
            logger.warning("Missing 閣法番号 on detail id=%d", detail_id)

        status = _get_text(fields.get("成立状況")) or ""
        if not status:
            logger.warning("Missing 成立状況 on detail id=%d", detail_id)

        submitter = _get_text(fields.get("主管省庁")) or ""
        if not submitter:
            logger.warning("Missing 主管省庁 on detail id=%d", detail_id)

        cabinet_decision_at = _extract_time_attr(fields.get("閣議決定日"))
        if cabinet_decision_at is None:
            logger.warning("Missing 閣議決定日 on detail id=%d", detail_id)

        submitted_at = _extract_time_attr(fields.get("国会提出日"))
        if submitted_at is None:
            logger.warning("Missing 国会提出日 on detail id=%d", detail_id)

        reason = _extract_reason(fields.get("提出理由"))
        if reason is None:
            logger.warning("Missing 提出理由 on detail id=%d", detail_id)

        logger.info("Fetched CLB detail id=%d title=%s", detail_id, title)

        return BillDetail(
            id=f"clb-{detail_id}",
            type="kakuhou",
            title=title,
            reason=reason,
            diet_session=diet_session,
            bill_number=bill_number,
            submitter=submitter,
            submitted_at=submitted_at,
            cabinet_decision_at=cabinet_decision_at,
            status=status,
            source_url=url,
        )

    def scrape_session(self, diet_session: int) -> list[BillDetail]:
        """指定国会回次の閣法をすべて取得する（レート制限つき）。

        Args:
            diet_session: 国会回次（例: 221）

        Returns:
            BillDetail のリスト（リストページ掲載順）

        Raises:
            ValueError: 指定回次がランディングページに存在しない場合
        """
        sessions = self.list_session_ids()
        if diet_session not in sessions:
            raise ValueError(
                f"Diet session {diet_session} not found on CLB landing page"
            )
        list_page_id = sessions[diet_session]

        detail_ids = self.list_detail_ids(list_page_id)

        bills: list[BillDetail] = []
        for idx, detail_id in enumerate(detail_ids):
            if idx > 0 and self.request_delay > 0:
                time.sleep(self.request_delay)
            try:
                bills.append(self.get_bill_detail(detail_id))
            except (requests.HTTPError, ValueError) as exc:
                logger.warning(
                    "Failed to fetch CLB detail id=%d: %s", detail_id, exc
                )
        return bills


# ---------------------------------------------------------------------- helpers


def _parse_dl_pairs(dl: Tag) -> dict[str, Tag]:
    """`<dl>` 内の dt/dd を交互に辿り、dtテキスト → dd要素 の dict を返す。"""
    result: dict[str, Tag] = {}
    children = dl.find_all(["dt", "dd"])
    i = 0
    while i < len(children):
        dt = children[i]
        if dt.name != "dt":
            i += 1
            continue
        dd: Tag | None = None
        if i + 1 < len(children) and children[i + 1].name == "dd":
            dd = children[i + 1]
            i += 2
        else:
            i += 1
        if dd is None:
            continue
        key = dt.get_text(strip=True)
        if key:
            result[key] = dd
    return result


def _get_text(dd: Tag | None) -> str | None:
    """dd要素からテキストを取り出す。空文字列は None として扱う。"""
    if dd is None:
        return None
    text = dd.get_text(strip=True)
    return text or None


def _extract_time_attr(dd: Tag | None) -> str | None:
    """dd 内の `<time datetime="YYYY-MM-DD">` の datetime 属性を返す。"""
    if dd is None:
        return None
    time_tag = dd.find("time")
    if not isinstance(time_tag, Tag):
        return None
    datetime_attr = time_tag.get("datetime")
    if not datetime_attr:
        return None
    return str(datetime_attr).strip() or None


def _extract_reason(dd: Tag | None) -> str | None:
    """提出理由 dd から本文テキストを抽出する。

    通常 `<p>` が1つ入っているが、複数段落や `<p>` 無しのケースにも対応。
    """
    if dd is None:
        return None
    paragraphs = dd.find_all("p")
    if paragraphs:
        text = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
    else:
        text = dd.get_text(strip=True)
    text = text.strip()
    return text or None
